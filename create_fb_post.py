import requests
import logging, sys
from autofb.config import ConfigError, load_config
from utils import random_utils, comment
import schedule, time 


# path to get image to post
img_path = './img'
# API endpoint for creating a new post
api_version="v25.0"
api_url = f'https://graph.facebook.com/{api_version}'

# logging config
root = logging.getLogger()
root.setLevel(logging.DEBUG)
handler = logging.StreamHandler(sys.stdout)
handler.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
root.addHandler(handler)


# create post with photos via graph api
def create_post(page_id, message, access_token, photo_path, excel_file):
    post_url = f'{api_url}/{page_id}/photos'
    payload = {
        "access_token": access_token,
        "message": message
        }
    try:
        with open(photo_path, 'rb') as photo:
            files = {'source': photo}
            response = requests.post(post_url, data=payload, files=files, timeout=60)
        response_data = response.json()
        logging.debug(response_data)
        if 'post_id' in response_data:
            logging.info(f"Success - PostID: {response_data['post_id']}")
            post_id = response_data['post_id']
            comment_msg, link = comment.random_comment_from_excel(excel_file)
            time.sleep(12)
            comment.comment_on_post(post_id, comment_msg, link, access_token)
        else:
            logging.error(f"Failed to create new post: {response_data}")
    except requests.RequestException as e:
        logging.error(f"Request Exception: {e}")
    except ValueError as ve:
        logging.error(f"ValueError: {ve}")
    except Exception as ex:
        logging.error(f"An unexpected error occurred: {ex}")


def main():
    config = load_config()
    for page_id, access_token in config.pages.page_tokens():
        message = random_utils.random_caption(config.excel.caption_file)
        logging.debug(f"message caption: {message}")
        photo_path = random_utils.random_file_from_folder(img_path)
        create_post(page_id, message, access_token, photo_path, config.excel.path)
schedule.every().day.at("04:00").do(main)
schedule.every().day.at("08:00").do(main)
schedule.every().day.at("12:00").do(main)
schedule.every().day.at("16:00").do(main)
#schedule.every().day.at("18:00").do(main)
schedule.every().day.at("20:00").do(main)
schedule.every().day.at("00:00").do(main)
#schedule.every().day.at("16:00").do(main)
#schedule.every().day.at("16:10").do(main)


if __name__ == "__main__":
    try:
        main()
    except ConfigError as exc:
        logging.error("Invalid configuration: %s", exc)
        raise SystemExit(2)
    while True:
        schedule.run_pending()
        time.sleep(1000)  # sleep 1000s, avoid cpu load 
