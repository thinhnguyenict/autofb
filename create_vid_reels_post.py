import os
import requests
import logging
import sys
import schedule
import time
from autofb.config import ConfigError, load_config
from utils import random_utils, comment

# Cấu hình thư mục chứa video
VIDEO_FOLDER = './videos'

# Graph API v22.0
API_VERSION = "v22.0"
GRAPH_URL = f'https://graph.facebook.com/{API_VERSION}'

# Cấu hình logging
logger = logging.getLogger()
logger.setLevel(logging.DEBUG)
handler = logging.StreamHandler(sys.stdout)
handler.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)


def upload_reel(page_id, caption, access_token, video_path, excel_file):
    """Đăng Reels Facebook bằng 3 bước upload_phase: start → upload → finish"""

    if not os.path.exists(video_path):
        logger.error(f"Không tìm thấy video: {video_path}")
        return

    logger.info(f"--- Bắt đầu quy trình đăng Reels ---")

    # STEP 1: Start phase
    start_url = f"{GRAPH_URL}/{page_id}/video_reels"
    start_payload = {
        "upload_phase": "start",
        "access_token": access_token
    }

    try:
        start_res = requests.post(start_url, data=start_payload)
        start_data = start_res.json()
        logger.debug(f"Start response: {start_data}")

        if 'upload_url' not in start_data or 'video_id' not in start_data:
            logger.error(f"Không lấy được upload_url hoặc video_id: {start_data}")
            return

        upload_url = start_data['upload_url']
        video_id = start_data['video_id']

        # STEP 2: Upload video
        with open(video_path, 'rb') as f:
            video_bytes = f.read()

        upload_res = requests.post(upload_url, data=video_bytes, headers={
            'Content-Type': 'application/octet-stream'
        })

        if upload_res.status_code != 200:
            logger.error(f"Lỗi upload video lên upload_url: {upload_res.text}")
            return

        # STEP 3: Finish phase
        finish_payload = {
            "upload_phase": "finish",
            "video_id": video_id,
            "description": caption,
            "access_token": access_token
        }

        finish_res = requests.post(start_url, data=finish_payload)
        finish_data = finish_res.json()
        logger.debug(f"Finish response: {finish_data}")

        if 'id' in finish_data:
            logger.info(f"Đăng Reels thành công - Video ID: {finish_data['id']}")
            # Gửi bình luận
            comment_msg, link = comment.random_comment_from_excel(excel_file)
            time.sleep(12)
            comment.comment_on_post(finish_data['id'], comment_msg, link, access_token)
        else:
            logger.error(f"Lỗi khi kết thúc upload Reels: {finish_data}")

    except Exception as e:
        logger.error(f"Lỗi tổng quát khi upload Reels: {str(e)}")


def main():
    """Đăng video Reels cho từng fanpage trong danh sách"""
    config = load_config()
    for page_id, access_token in config.pages.page_tokens():
        caption = random_utils.random_caption(config.excel.caption_file)
        video_file = random_utils.random_file_from_folder(VIDEO_FOLDER)

        logger.info(f"Video được chọn: {video_file}")
        logger.info(f"Caption được chọn: {caption}")

        upload_reel(page_id, caption, access_token, video_file, config.excel.path)


# Lịch đăng video
schedule.every().day.at("06:00").do(main)
schedule.every().day.at("10:00").do(main)
schedule.every().day.at("14:00").do(main)
schedule.every().day.at("18:00").do(main)
schedule.every().day.at("22:00").do(main)
schedule.every().day.at("02:00").do(main)

if __name__ == "__main__":
    logger.info("Bắt đầu đăng Reels Facebook tự động...")
    try:
        main()
    except ConfigError as exc:
        logger.error("Invalid configuration: %s", exc)
        raise SystemExit(2)
    while True:
        schedule.run_pending()
        time.sleep(60)
