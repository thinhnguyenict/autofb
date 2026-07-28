import requests
import logging, sys
from autofb.config import ConfigError, load_config
from utils import random_utils, comment
import schedule, time

# Đường dẫn chứa video
video_path = './videos'
# API endpoint cho Facebook Graph API
api_version = "v22.0"
api_url = f'https://graph.facebook.com/{api_version}'

# Cấu hình logging
root = logging.getLogger()
root.setLevel(logging.DEBUG)
handler = logging.StreamHandler(sys.stdout)
handler.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
root.addHandler(handler)

# Tải lên video reels thông qua Graph API
def upload_video(page_id, message, access_token, post_url, video_file_path, excel_file):
    post_url = f'{post_url}/{page_id}/videos'
    payload = {
        "access_token": access_token,
        "description": message  # Mô tả của video
    }
    try:
        with open(video_file_path, 'rb') as video:
            response = requests.post(
                post_url, data=payload, files={'source': video}, timeout=120
            ).json()
        logging.debug(response)
        if 'id' in response:
            logging.info(f"Success - VideoID: {response['id']}")
            video_id = response['id']
            comment_msg, link = comment.random_comment_from_excel(excel_file)
            time.sleep(12)
            comment.comment_on_post(video_id, comment_msg, link, access_token)
        else:
            logging.error("Failed to upload video")
    except requests.RequestException as e:
        logging.error(f"Request Exception: {e}")
    except ValueError as ve:
        logging.error(f"ValueError: {ve}")
    except Exception as ex:
        logging.error(f"An unexpected error occurred: {ex}")

# Hàm chính
def main():
    config = load_config()
    for page_id, access_token in config.pages.page_tokens():
        message = random_utils.random_caption(config.excel.caption_file)
        logging.debug(f"Video caption: {message}")
        video_file_path = random_utils.random_file_from_folder(video_path)
        upload_video(page_id, message, access_token, api_url, video_file_path, config.excel.path)

# Lập lịch tự động đăng video reels
schedule.every().day.at("06:00").do(main)
schedule.every().day.at("10:00").do(main)
schedule.every().day.at("14:00").do(main)
schedule.every().day.at("18:00").do(main)
schedule.every().day.at("22:00").do(main)
schedule.every().day.at("02:00").do(main)

if __name__ == "__main__":
    try:
        main()
    except ConfigError as exc:
        logging.error("Invalid configuration: %s", exc)
        raise SystemExit(2)
    while True:
        schedule.run_pending()
        time.sleep(1000)  # sleep 1000s, tránh CPU quá tải
