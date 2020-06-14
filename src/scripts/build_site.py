import html
import os
import re
import shutil
from collections import OrderedDict
from configparser import RawConfigParser
from datetime import datetime
from glob import glob
from json import dumps
from time import strptime, time, strftime
from typing import Dict, List, Tuple

from PIL import Image
from jinja2 import Environment, FileSystemLoader, TemplateNotFound
from pytz import timezone

from build_rss_feed import build_rss_feed

VERSION = "0.1.0"

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
BASE_DIRECTORY = None
LINKS_LIST = []


def path(rel_path: str):
    if rel_path.startswith("/"):
        return "/" + BASE_DIRECTORY + rel_path
    return rel_path


def str_to_list(s, delimiter=","):
    """
    split(), but with extra stripping of white space and leading/trailing delimiters
    :param s:
    :param delimiter:
    :return:
    """
    if not s:
        return []
    return [item.strip(" ") for item in s.strip(delimiter + " ").split(delimiter)]


def get_links_list(comic_info: RawConfigParser):
    link_list = []
    for option in comic_info.options("Links Bar"):
        link_list.append({"name": option, "url": path(comic_info.get("Links Bar", option))})
    return link_list


def get_pages_list(comic_info: RawConfigParser):
    page_list = []
    for option in comic_info.options("Pages"):
        page_list.append({"template_name": option, "title": path(comic_info.get("Pages", option))})
    return page_list


def delete_output_file_space(comic_info: RawConfigParser=None):
    shutil.rmtree("comic", ignore_errors=True)
    if os.path.isfile("feed.xml"):
        os.remove("feed.xml")
    if comic_info is None:
        comic_info = read_info("your_content/comic_info.ini")
    for page in get_pages_list(comic_info):
        if os.path.isfile(page["template_name"] + ".html"):
            os.remove(page["template_name"] + ".html")


def setup_output_file_space(comic_info: RawConfigParser):
    # Clean workspace, i.e. delete old files
    delete_output_file_space(comic_info)
    # Create directories if needed
    os.makedirs("comic", exist_ok=True)


def read_info(filepath, to_dict=False):
    with open(filepath) as f:
        info_string = f.read()
    if not re.search(r"^\[.*?\]", info_string):
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


def get_page_info_list(comic_info: RawConfigParser) -> Tuple[List[Dict], int]:
    date_format = comic_info.get("Comic Settings", "Date format")
    tzinfo = timezone(comic_info.get("Comic Settings", "Timezone"))
    local_time = datetime.now(tz=tzinfo)
    print(f"Local time is {local_time}")
    page_info_list = []
    scheduled_post_count = 0
    for page_path in glob("your_content/comics/*/"):
        page_info = read_info(f"{page_path}info.ini", to_dict=True)
        post_date = tzinfo.localize(datetime.strptime(page_info["Post date"], date_format))
        if post_date > local_time:
            scheduled_post_count += 1
            # Post date is in the future, so delete the folder with the resources
            if comic_info.getboolean("Comic Settings", "Delete scheduled posts"):
                shutil.rmtree(page_path)
        else:
            page_info["page_name"] = os.path.basename(page_path.strip("\\"))
            page_info["Storyline"] = page_info.get("Storyline", "")
            page_info["Characters"] = str_to_list(page_info.get("Characters", ""))
            page_info["Tags"] = str_to_list(page_info.get("Tags", ""))
            page_info_list.append(page_info)

    page_info_list = sorted(
        page_info_list,
        key=lambda x: (strptime(x["Post date"], date_format), x["page_name"])
    )
    return page_info_list, scheduled_post_count


def save_page_info_json_file(page_info_list: List, scheduled_post_count: int):
    d = {
        "page_info_list": page_info_list,
        "scheduled_post_count": scheduled_post_count
    }
    with open("comic/page_info_list.json", "w") as f:
        f.write(dumps(d))


def get_ids(comic_list: List[Dict], index):
    first_id = comic_list[0]["page_name"]
    last_id = comic_list[-1]["page_name"]
    return {
        "first_id": first_id,
        "previous_id": first_id if index == 0 else comic_list[index - 1]["page_name"],
        "current_id": comic_list[index]["page_name"],
        "next_id": last_id if index == (len(comic_list) - 1) else comic_list[index + 1]["page_name"],
        "last_id": last_id
    }


def create_comic_data(comic_info: RawConfigParser, page_info: dict,
                      first_id: str, previous_id: str, current_id: str, next_id: str, last_id: str):
    print("Building page {}...".format(page_info["page_name"]))
    archive_post_date = strftime(comic_info.get("Archive", "Date format"),
                                 strptime(page_info["Post date"], comic_info.get("Comic Settings", "Date format")))
    with open(f"your_content/comics/{page_info['page_name']}/post.html", "rb") as f:
        post_html = f.read().decode("utf-8")
    return {
        "page_name": page_info["page_name"],
        "filename": page_info["Filename"],
        "comic_path": "your_content/comics/{}/{}".format(
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
        "current_id": current_id,
        "next_id": next_id,
        "last_id": last_id,
        "page_title": page_info["Title"],
        "post_date": page_info["Post date"],
        "archive_post_date": archive_post_date,
        "storyline": None if "Storyline" not in page_info else page_info["Storyline"],
        "characters": page_info["Characters"],
        "tags": page_info["Tags"],
        "post_html": post_html
    }


def build_comic_data_dicts(comic_info: RawConfigParser, page_info_list: List[Dict]) -> List[Dict]:
    comic_data_dicts = []
    for i, page_info in enumerate(page_info_list):
        comic_dict = create_comic_data(comic_info, page_info, **get_ids(page_info_list, i))
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


def save_image(im, path):
    try:
        im.save(path)
    except OSError as e:
        if str(e) == "cannot write mode RGBA as JPEG":
            # Get rid of transparency
            bg = Image.new("RGB", im.size, "WHITE")
            bg.paste(im, (0, 0), im)
            bg.save(path)
        else:
            raise


def process_comic_image(comic_info, comic_page_path, create_thumbnails, create_low_quality):
    section = "Image Reprocessing"
    comic_page_dir = os.path.dirname(comic_page_path)
    comic_page_name, comic_page_ext = os.path.splitext(os.path.basename(comic_page_path))
    with open(comic_page_path, "rb") as f:
        im = Image.open(f)
        if create_thumbnails:
            thumbnail_path = os.path.join(comic_page_dir, comic_page_name + "_thumbnail.jpg")
            if comic_info.getboolean(section, "Overwrite existing images") or not os.path.isfile(thumbnail_path):
                print(f"Creating thumbnail for {comic_page_name}")
                thumb_im = resize(im, comic_info.get(section, "Thumbnail size"))
                save_image(thumb_im, thumbnail_path)
        if create_low_quality:
            file_type = comic_info.get(section, "Low-quality file type")
            low_quality_path = os.path.join(comic_page_dir, comic_page_name + "_low_quality." + file_type.lower())
            if comic_info.getboolean(section, "Overwrite existing images") or not os.path.isfile(low_quality_path):
                print(f"Creating low quality version of {comic_page_name}")
                save_image(im, low_quality_path)


def process_comic_images(comic_info, comic_data_dicts: List[Dict]):
    section = "Image Reprocessing"
    create_thumbnails = comic_info.getboolean(section, "Create thumbnails")
    create_low_quality = comic_info.getboolean(section, "Create low-quality versions of images")
    if create_thumbnails or create_low_quality:
        for comic_data in comic_data_dicts:
            process_comic_image(comic_info, comic_data["comic_path"], create_thumbnails, create_low_quality)


def get_storylines(comic_data_dicts: List[Dict]) -> List[Dict[str, List]]:
    # Start with an OrderedDict, so we can easily drop the pages we encounter in the proper buckets, while keeping
    # their proper order
    storylines_dict = OrderedDict()
    for comic_data in comic_data_dicts:
        storyline = comic_data["storyline"]
        if storyline:
            if storyline not in storylines_dict.keys():
                storylines_dict[storyline] = []
            storylines_dict[storyline].append(comic_data)

    # Convert the OrderedDict to a list of dicts, so it's more easily accessible by the Jinja2 templates later
    storylines = []
    for name, pages in storylines_dict.items():
        storylines.append({
            "name": name,
            "pages": pages
        })
    return storylines


def write_to_template(template_path, html_path, data_dict=None):
    if data_dict is None:
        data_dict = {}
    try:
        template = JINJA_ENVIRONMENT.get_template(template_path)
    except TemplateNotFound:
        print("Template file {} not found".format(template_path))
    else:
        with open(html_path, "wb") as f:
            rendered_template = template.render(**data_dict)
            f.write(bytes(rendered_template, "utf-8"))


def write_html_files(comic_info: RawConfigParser, comic_data_dicts: List[Dict], global_values: Dict):
    # Write individual comic pages
    print("Writing {} comic pages...".format(len(comic_data_dicts)))
    for comic_data_dict in comic_data_dicts:
        html_path = "comic/{}.html".format(comic_data_dict["page_name"])
        comic_data_dict.update(global_values)
        write_to_template("comic.tpl", html_path, comic_data_dict)
    write_other_pages(comic_info, comic_data_dicts)


def write_other_pages(comic_info: RawConfigParser, comic_data_dicts: List[Dict]):
    last_comic_page = comic_data_dicts[-1]
    pages_list = get_pages_list(comic_info)
    for page in pages_list:
        template_name = page["template_name"] + ".tpl"
        html_path = page["template_name"] + ".html"
        data_dict = {}
        data_dict.update(last_comic_page)
        if page["title"]:
            data_dict["page_title"] = page["title"]
        print("Writing {}...".format(html_path))
        write_to_template(template_name, html_path, data_dict)


def print_processing_times(processing_times: List[Tuple[str, float]]):
    last_processed_time = None
    print("")
    for name, t in processing_times:
        if last_processed_time is not None:
            print("{}: {:.2f} ms".format(name, (t - last_processed_time) * 1000))
        last_processed_time = t
    print("{}: {:.2f} ms".format("Total time", (processing_times[-1][1] - processing_times[0][1]) * 1000))


def main():
    global BASE_DIRECTORY
    processing_times = [("Start", time())]

    # Get site-wide settings for this comic
    comic_info = read_info("your_content/comic_info.ini")
    comic_domain = None
    if "GITHUB_REPOSITORY" in os.environ:
        repo_author, BASE_DIRECTORY = os.environ["GITHUB_REPOSITORY"].split("/")
        comic_domain = f"http://{repo_author}.github.io"
    if comic_info.has_option("Comic Info", "Comic domain"):
        comic_domain = comic_info.get("Comic Info", "Comic domain").rstrip("/")
    if comic_info.has_option("Comic Info", "Comic subdirectory"):
        BASE_DIRECTORY = comic_info.get("Comic Info", "Comic subdirectory").strip("/")
    if not comic_domain or not BASE_DIRECTORY:
        raise ValueError(
            'Set "Comic domain" and "Comic subdirectory" in the [Comic Info] section of your comic_info.ini file '
            'before building your site locally. Please see the comic_git wiki for more information.'
        )
    comic_url = comic_domain + '/' + BASE_DIRECTORY

    processing_times.append(("Get comic settings", time()))

    # Setup output file space
    setup_output_file_space(comic_info)
    processing_times.append(("Setup output file space", time()))

    # Get the info for all pages, sorted by Post Date
    page_info_list, scheduled_post_count = get_page_info_list(comic_info)
    print([p["page_name"] for p in page_info_list])
    processing_times.append(("Get info for all pages", time()))

    # Save page_info_list.json file for use by other pages
    save_page_info_json_file(page_info_list, scheduled_post_count)
    processing_times.append(("Save page_info_list.json file", time()))

    # Build full comic data dicts, to build templates with
    comic_data_dicts = build_comic_data_dicts(comic_info, page_info_list)
    processing_times.append(("Build full comic data dicts", time()))

    # Create low-res and thumbnail versions of all the comic pages
    process_comic_images(comic_info, comic_data_dicts)
    processing_times.append(("Process comic images", time()))

    # Write page info to comic HTML pages
    global_values = {
        "autogenerate_warning": AUTOGENERATE_WARNING,
        "version": VERSION,
        "comic_title": comic_info.get("Comic Info", "Comic name"),
        "comic_description": comic_info.get("Comic Info", "Description"),
        "comic_url": comic_url,
        "base_dir": BASE_DIRECTORY,
        "links_list": get_links_list(comic_info),
        "use_thumbnails": comic_info.getboolean("Archive", "Use thumbnails"),
        "storylines": get_storylines(comic_data_dicts),
    }
    write_html_files(comic_info, comic_data_dicts, global_values)
    processing_times.append(("Write HTML files", time()))

    # Build RSS feed
    build_rss_feed(comic_info, comic_data_dicts)
    processing_times.append(("Build RSS feed", time()))

    print_processing_times(processing_times)


if __name__ == "__main__":
    main()
