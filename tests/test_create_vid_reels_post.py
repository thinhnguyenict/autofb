import unittest
import types
import sys
from unittest.mock import MagicMock, mock_open, patch

sys.modules.setdefault("utils.random_utils", types.ModuleType("utils.random_utils"))
comment_module = sys.modules.setdefault("utils.comment", types.ModuleType("utils.comment"))
setattr(comment_module, "random_comment_from_excel", lambda *_args, **_kwargs: ("", ""))
setattr(comment_module, "comment_on_post", lambda *_args, **_kwargs: None)

import create_vid_reels_post


class _ResponseWithGuard:
    def __init__(self, payload):
        self.payload = payload
        self.status_checked = False

    def raise_for_status(self):
        self.status_checked = True

    def json(self):
        if not self.status_checked:
            raise AssertionError("raise_for_status must be called before json")
        return self.payload


class UploadReelTests(unittest.TestCase):
    @patch("create_vid_reels_post.time.sleep")
    @patch("create_vid_reels_post.comment.comment_on_post")
    @patch("create_vid_reels_post.comment.random_comment_from_excel", return_value=("msg", "link"))
    @patch("create_vid_reels_post.requests.post")
    @patch("create_vid_reels_post.os.path.exists", return_value=True)
    def test_upload_reel_uses_timeout_and_checks_http_before_json(
        self, _exists, post_mock, _random_comment, _comment_on_post, _sleep
    ):
        start_response = _ResponseWithGuard({"upload_url": "https://upload.example", "video_id": "video-1"})
        upload_response = MagicMock()
        finish_response = _ResponseWithGuard({"id": "video-1"})
        post_mock.side_effect = [start_response, upload_response, finish_response]

        with patch("builtins.open", mock_open(read_data=b"video-bytes")):
            create_vid_reels_post.upload_reel("page-1", "caption", "token-1", "/tmp/video.mp4", "comments.xlsx")

        self.assertEqual(post_mock.call_count, 3)
        for call in post_mock.call_args_list:
            self.assertEqual(call.kwargs["timeout"], create_vid_reels_post.REQUEST_TIMEOUT)
        upload_response.raise_for_status.assert_called_once()


if __name__ == "__main__":
    unittest.main()
