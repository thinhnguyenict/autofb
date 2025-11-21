
curl -X POST \
  "https://graph-video.facebook.com/v19.0/471948829668444/videos" \
  -F "upload_phase=start" \
  -F "access_token=EAAOZCt57jvjsBOZCabpiKsseXAQcUXdQ7acBV1xsjTZABZCFVWjRu4FO0vZACJpKjehvGtjsHtFIHvgPJIlngCx2ZArHLnp7O6kRQVXxvZCdLcoVSzyJzWVeLhctfa1zSlNhI8q6ih441EfmBkGxYM1I0mCm6VOwhbdxMzbWPG3JSYosIAPHRSQNRWZAoZBjCKE4m" \
  -F "file_size=22420886"
=> {"video_id":"984704296546048","start_offset":"0","end_offset":"1048576","upload_session_id":"984704306546047"}%

curl -X POST \
  "https://graph-video.facebook.com/v19.0/471948829668444/videos" \
  -F "upload_phase=transfer" \
  -F "upload_session_id=984704306546047" \
  -F "access_token=EAAOZCt57jvjsBOZCabpiKsseXAQcUXdQ7acBV1xsjTZABZCFVWjRu4FO0vZACJpKjehvGtjsHtFIHvgPJIlngCx2ZArHLnp7O6kRQVXxvZCdLcoVSzyJzWVeLhctfa1zSlNhI8q6ih441EfmBkGxYM1I0mCm6VOwhbdxMzbWPG3JSYosIAPHRSQNRWZAoZBjCKE4m" \
  -F "start_offset=0" \
  -F "video_file_chunk=@/Users/tuyentd/Downloads/sample-5s.mp4"
=>> {"start_offset":"2848208","end_offset":"3848208"}%



curl -X POST \
  "https://graph-video.facebook.com/v19.0/471948829668444/videos" \
  -F "upload_phase=finish" \
  -F "access_token=EAAOZCt57jvjsBOZCabpiKsseXAQcUXdQ7acBV1xsjTZABZCFVWjRu4FO0vZACJpKjehvGtjsHtFIHvgPJIlngCx2ZArHLnp7O6kRQVXxvZCdLcoVSzyJzWVeLhctfa1zSlNhI8q6ih441EfmBkGxYM1I0mCm6VOwhbdxMzbWPG3JSYosIAPHRSQNRWZAoZBjCKE4m" \
  -F "upload_session_id=984704306546047"

=>> {"success":true}%
