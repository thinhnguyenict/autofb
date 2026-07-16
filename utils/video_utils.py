"""Experimental Reels upload helper.

This module deliberately has no embedded credentials and performs no network call
on import. Call ``upload_video`` with a Page ID, a valid token and a file path.
"""
from __future__ import annotations

import logging
from pathlib import Path

import requests


def upload_video(page_id: str, access_token: str, video_path: str | Path) -> dict:
    url = f"https://rupload.facebook.com/video-upload/v21.0/{page_id}/video_reels"
    with Path(video_path).open("rb") as video:
        response = requests.post(
            url,
            files={"data": video},
            data={
                "title": "",
                "description": "",
                "access_token": access_token,
            },
            timeout=120,
        )
    response.raise_for_status()
    payload = response.json()
    logging.info("Reels upload response received for page %s", page_id)
    return payload
