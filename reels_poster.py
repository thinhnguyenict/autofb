import requests
import logging, sys, json
from utils import random_utils, comment
import schedule, time

# Đường dẫn chứa video
video_path = './videos'
# API endpoint cho Facebook Graph API
api_version = "v22.0"
api_url = f'https://graph.facebook.com/{api_version}'

# Đọc cấu hình từ file JSON
with open('./config.json') as f:
    config = json.load(f)
excel_file = config['excel']['path']
captions_file = config['excel']['caption_file']
page_id_list = config['pages']['page_id']
access_token_list = config['pages']['access_token']
page_access_tokens = dict(zip(page_id_list, access_token_list))

# Cấu hình logging
root = logging.getLogger()
root.setLevel(logging.DEBUG)
handler = logging.StreamHandler(sys.stdout)
handler.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
root.addHandler(handler)

# Tải lên video reels thông qua Graph API
def upload_video(page_id, message, access_token, post_url, video_file_path):
    post_url = f'{post_url}/{page_id}/videos'
    payload = {
        "access_token": access_token,
        "description": message  # Mô tả của video
    }
    files = {
        'source': open(video_file_path, 'rb')  # Tải file video
    }
    try:
        response = requests.post(post_url, data=payload, files=files).json()
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
    for page_id, access_token in page_access_tokens.items():
        message = random_utils.random_caption(captions_file)
        logging.debug(f"Video caption: {message}")
        video_file_path = random_utils.random_file_from_folder(video_path)
        upload_video(page_id, message, access_token, api_url, video_file_path)

# Lập lịch tự động đăng video reels
schedule.every().day.at("06:00").do(main)
schedule.every().day.at("10:00").do(main)
schedule.every().day.at("14:00").do(main)
schedule.every().day.at("18:00").do(main)
schedule.every().day.at("22:00").do(main)
schedule.every().day.at("02:00").do(main)

if __name__ == '''__main__''':
    main()
    while True:
        schedule.run_pending()
        time.sleep(1000)  # sleep 1000s, tránh CPU quá tải
