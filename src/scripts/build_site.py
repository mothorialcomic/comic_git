import html
import os
import random
import re
import shutil
import string
from configparser import RawConfigParser
from glob import glob
from json import dumps
from os.path import isfile

from PIL import Image
from time import strptime, localtime, time, strftime
from typing import Dict, List, Tuple

from jinja2 import Environment, FileSystemLoader

from build_rss_feed import build_rss_feed

JINJA_ENVIRONMENT = Environment(
    loader=FileSystemLoader("src/templates")
)
AUTOGENERATE_WARNING = """<!--
!! DO NOT EDIT THIS FILE !!
It is auto-generated and any work you do here will be replaced the next time this page is generated.
If you want to edit any of these files, edit their *.tpl versions in src/templates.
-->
"""
COMIC_TITLE = ""
BASE_DIRECTORY = os.path.basename(os.getcwd())
LINKS_LIST = []


def path(rel_path: str):
    if rel_path.startswith("/"):
        return "/" + BASE_DIRECTORY + rel_path
    return rel_path


def get_links_list(comic_info: RawConfigParser):
    link_list = []
    for option in comic_info.options("Links Bar"):
        link_list.append({"name": option, "url": path(comic_info.get("Links Bar", option))})
    return link_list


def delete_output_file_space():
    shutil.rmtree("comic", ignore_errors=True)
    for f in ["index.html", "archive.html", "tagged.html", "feed.xml"]:
        if os.path.isfile(f):
            os.remove(f)


def setup_output_file_space():
    # Clean workspace, i.e. delete old files
    delete_output_file_space()
    # Create directories if needed
    os.makedirs("comic", exist_ok=True)


def read_info(filepath, to_dict=False, might_be_scheduled=True):
    if might_be_scheduled and not isfile(filepath):
        scheduled_files = glob(filepath + ".*")
        if not scheduled_files:
            raise FileNotFoundError(filepath)
        filepath = scheduled_files[0]
    with open(filepath) as f:
        info_string = f.read()
    if not re.search("^\[.*?\]", info_string):
        # print(filepath + " has no section")
        info_string = "[DEFAULT]\n" + info_string
    info = RawConfigParser()
    info.optionxform = str
    info.read_string(info_string)
    if to_dict:
        # TODO: Support multiple sections
        if not list(info.keys()) == ["DEFAULT"]:
            raise NotImplementedError("Configs with multiple sections not yet supported")
        return dict(info["DEFAULT"])
    return info


def schedule_files(folder_path):
    for filepath in glob(folder_path + "/*"):
        if not re.search(r"\.[a-z]{10}$", filepath):
            # Add an extra extension to the filepath, a period followed by ten random lower case characters
            os.rename(filepath, filepath + "." + "".join(random.choices(string.ascii_lowercase, k=10)))


def unschedule_files(folder_path):
    for filepath in glob(folder_path + "/*"):
        if re.search(r"\.[a-z]{10}$", filepath):
            os.rename(filepath, filepath[:-11])


def get_page_info_list(date_format: str) -> List[Dict]:
    local_time = localtime()
    print("Local time is {}".format(strftime('%Y-%m-%dT%H:%M:%SZ', local_time)))
    page_info_list = []
    for page_path in glob("your_content/comics/*"):
        page_info = read_info("{}/info.ini".format(page_path), to_dict=True, might_be_scheduled=True)
        if strptime(page_info["Post date"], date_format) > local_time:
            # Post date is in the future, so mark all the files as .scheduled so they don't show up online
            schedule_files(page_path)
        else:
            # Post date is in the past, so publish the comic files
            unschedule_files(page_path)
            page_info["page_name"] = os.path.basename(page_path)
            page_info["Tags"] = [tag.strip() for tag in page_info["Tags"].strip().split(",")]
            page_info_list.append(page_info)

    page_info_list = sorted(
        page_info_list,
        key=lambda x: (strptime(x["Post date"], date_format), x["page_name"])
    )
    return page_info_list


def get_ids(comic_list: List[Dict], index):
    first_id = comic_list[0]["page_name"]
    last_id = comic_list[-1]["page_name"]
    return {
        "first_id": first_id,
        "previous_id": first_id if index == 0 else comic_list[index - 1]["page_name"],
        "next_id": last_id if index == (len(comic_list) - 1) else comic_list[index + 1]["page_name"],
        "last_id": last_id
    }


def create_comic_data(page_info: dict, first_id: str, previous_id: str, next_id: str, last_id: str):
    print("Building page {}...".format(page_info["page_name"]))
    with open("your_content/comics/{}/post.html".format(page_info["page_name"]), "rb") as f:
        post_html = f.read().decode("utf-8")
    return {
        "page_name": page_info["page_name"],
        "filename": page_info["Filename"],
        "comic_path": "../your_content/comics/{}/{}".format(
            page_info["page_name"],
            page_info["Filename"]
        ),
        "thumbnail_path": "your_content/comics/{}/{}".format(
            page_info["page_name"],
            os.path.splitext(page_info["Filename"])[0] + "_thumbnail.jpg"
        ),
        "alt_text": html.escape(page_info["Alt text"]),
        "first_id": first_id,
        "previous_id": previous_id,
        "next_id": next_id,
        "last_id": last_id,
        "page_title": page_info["Title"],
        "post_date": page_info["Post date"],
        "tags": page_info["Tags"],
        "post_html": post_html
    }


def build_comic_data_dicts(page_info_list: List[Dict]) -> List[Dict]:
    comic_data_dicts = []
    for i, page_info in enumerate(page_info_list):
        comic_dict = create_comic_data(page_info, **get_ids(page_info_list, i))
        comic_data_dicts.append(comic_dict)
    return comic_data_dicts


def resize(im, size):
    if "," in size:
        # Convert a string of the form "100, 36" into a 2-tuple of ints (100, 36)
        x, y = size.strip().split(",")
        new_size = (int(x.strip()), int(y.strip()))
    elif size.endswith("%"):
        # Convert a percentage (50%) into a new size (50, 18)
        size = float(size.strip().strip("%"))
        size = size / 100
        x, y = im.size
        new_size = (int(x * size), int(y * size))
    else:
        raise ValueError("Unknown resize value: {!r}".format(size))
    return im.resize(new_size)


def process_comic_image(comic_info, comic_page_path, create_thumbnails, create_low_quality):
    section = "Image Reprocessing"
    comic_page_dir = os.path.dirname(comic_page_path)
    comic_page_name, comic_page_ext = os.path.splitext(os.path.basename(comic_page_path))
    with open(comic_page_path, "rb") as f:
        im = Image.open(f)
        if create_thumbnails:
            thumb_im = resize(im, comic_info.get(section, "Thumbnail size"))
            thumb_im.save(os.path.join(comic_page_dir, comic_page_name + "_thumbnail.jpg"))
        if create_low_quality:
            file_type = comic_info.get(section, "Low-quality file type")
            im.save(os.path.join(comic_page_dir, comic_page_name + "_low_quality." + file_type.lower()))


def process_comic_images(comic_info, comic_data_dicts: List[Dict]):
    section = "Image Reprocessing"
    create_thumbnails = comic_info.getboolean(section, "Create thumbnails")
    create_low_quality = comic_info.getboolean(section, "Create low-quality versions of images")
    if create_thumbnails or create_low_quality:
        for comic_data in comic_data_dicts:
            process_comic_image(comic_info, comic_data["comic_path"][3:], create_thumbnails, create_low_quality)


def write_to_template(template_path, html_path, data_dict=None):
    if data_dict is None:
        data_dict = {}
    template = JINJA_ENVIRONMENT.get_template(template_path)
    with open(html_path, "wb") as f:
        rendered_template = template.render(
            autogenerate_warning=AUTOGENERATE_WARNING,
            comic_title=COMIC_TITLE,
            base_dir=BASE_DIRECTORY,
            links=LINKS_LIST,
            **data_dict
        )
        f.write(bytes(rendered_template, "utf-8"))


def write_comic_pages(comic_data_dicts: List[Dict], create_index_file=True):
    # Write individual comic pages
    for comic_data_dict in comic_data_dicts:
        html_path = "comic/{}.html".format(comic_data_dict["page_name"])
        write_to_template("comic.tpl", html_path, comic_data_dict)
    if create_index_file:
        # Write index redirect HTML page
        print("Building index page...")
        index_dict = {
            "last_id": comic_data_dicts[-1]["page_name"]
        }
        write_to_template("index.tpl", "index.html", index_dict)


def write_archive_page(comic_info: RawConfigParser, comic_data_dicts: List[Dict]):
    print("Building archive page...")
    archive_sections = []
    for section in comic_info.get("Archive", "Archive sections").strip().split(","):
        section = section.strip()
        pages = [comic_data for comic_data in comic_data_dicts
                 if section in comic_data["tags"]]
        archive_sections.append({
            "name": section,
            "pages": pages
        })
    write_to_template("archive.tpl", "archive.html", {
        "page_title": "Archive",
        "use_thumbnails": comic_info.getboolean("Archive", "Use thumbnails"),
        "archive_sections": archive_sections
    })


def write_tagged_page():
    print("Building tagged page...")
    write_to_template("tagged.tpl", "tagged.html", {"page_title": "Tagged posts"})


def write_infinite_scroll_page():
    print("Building infinite scroll page...")
    write_to_template("infinite_scroll.tpl", "infinite_scroll.html", {"page_title": "Infinite scroll"})


def print_processing_times(processing_times: List[Tuple[str, float]]):
    last_processed_time = None
    print("")
    for name, t in processing_times:
        if last_processed_time is not None:
            print("{}: {:.2f} ms".format(name, (t - last_processed_time) * 1000))
        last_processed_time = t
    print("{}: {:.2f} ms".format("Total time", (processing_times[-1][1] - processing_times[0][1]) * 1000))


def main():
    global COMIC_TITLE, LINKS_LIST
    processing_times = [("Start", time())]

    # Setup output file space
    setup_output_file_space()
    processing_times.append(("Setup output file space", time()))

    # Get site-wide settings for this comic
    comic_info = read_info("your_content/comic_info.ini")
    COMIC_TITLE = comic_info.get("Comic Settings", "Comic name")
    LINKS_LIST = get_links_list(comic_info)
    processing_times.append(("Get comic settings", time()))

    # Get the info for all pages, sorted by Post Date
    page_info_list = get_page_info_list(comic_info.get("Comic Settings", "Date format"))
    print([p["page_name"] for p in page_info_list])
    processing_times.append(("Get info for all pages", time()))

    # Save page_info_list.json file for use by other pages
    with open("comic/page_info_list.json", "w") as f:
        f.write(dumps(page_info_list))
    processing_times.append(("Save page_info_list.json file", time()))

    # Build full comic data dicts, to build templates with
    comic_data_dicts = build_comic_data_dicts(page_info_list)
    processing_times.append(("Build full comic data dicts", time()))

    # Create low-res and thumbnail versions of all the comic pages
    process_comic_images(comic_info, comic_data_dicts)
    processing_times.append(("Process comic images", time()))

    # Write page info to comic HTML pages
    write_comic_pages(comic_data_dicts)
    write_archive_page(comic_info, comic_data_dicts)
    write_tagged_page()
    write_infinite_scroll_page()
    processing_times.append(("Write HTML files", time()))

    # Build RSS feed
    build_rss_feed(comic_info, comic_data_dicts)
    processing_times.append(("Build RSS feed", time()))

    print_processing_times(processing_times)


if __name__ == "__main__":
    main()
