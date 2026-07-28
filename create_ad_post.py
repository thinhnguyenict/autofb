import json
import random
import logging
from autofb.config import ConfigError, load_config
from utils import picture_utils, ad_post_utils

API_VERSION = "v25.0"

logging.basicConfig(
    format='%(asctime)s %(levelname)s:%(message)s',
    level=logging.INFO)


def main():
    config = load_config()
    if not config.pages.page_names:
        raise ConfigError("pages.page_name is required for ad publishing")
    for page, name, token in zip(config.pages.page_ids, config.pages.page_names, config.pages.access_tokens, strict=True):
        logging.info("Preparing ad post for page %s (%s)", name, page)
        
        # random link for each page
        # fetch content from prepared excel file
        try:
            message, link, img_path, cell_index = ad_post_utils.read_excel(config.excel.path)
            print (message, link, img_path, cell_index)
        except TypeError:
            print(f"All posts are  published. \nPlease prepare the data again. File path: {config.excel.path}")
            quit()

        # TODO: choose types
        # functions = [picture_utils.create_picture_frame_2x2, picture_utils.create_picture_frame_2x3, picture_utils.create_picture_frame_3x2, picture_utils.create_picture_frame_5x3, picture_utils.create_picture_frame_3x5]
        functions = [picture_utils.create_picture_frame_5x3, picture_utils.create_picture_frame_2x3]
        # functions = [picture_utils.create_picture_frame_5x3]

        selected_function = random.choice(functions)
        print("Func: " + str(selected_function))
        selected_function(img_path)

        # img_url = picture_utils.upload_picture(img_file="/output/output.jpg")
        img_url = picture_utils.upload_self_hosted_picture(img_file="./output/output.jpg")
        logging.info("img_url " + img_url)


        # get ad post id and publish post
        ad_post_data = json.loads(
            ad_post_utils.create_ad_post(
                img_url, message, link, page, token, config.pages.act_id, api_version=API_VERSION
            )
        )
        ad_post_id = ad_post_data["id"]

        import time; time.sleep(40) #wait till the post can be fetched from facebook (fb workflow)
        effective_object_story_id = ad_post_utils.get_ad_effective_object_story_id(
            ad_post_id, token, api_version=API_VERSION
        )
        print(effective_object_story_id)
        ad_post_utils.publish_ad_post(token, effective_object_story_id, api_version=API_VERSION)
        ad_post_utils.update_publish_status(config.excel.path, cell_index)
        print(f"Done publishing post to {name} page")

if __name__ == "__main__":
    try:
        main()
    except ConfigError as exc:
        logging.error("Invalid configuration: %s", exc)
        raise SystemExit(2)
