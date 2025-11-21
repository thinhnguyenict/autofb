#write out current crontab
crontab -l > auto-cron
#echo new cron into cron file
# echo "0 */1 * * * python3 /root/autopost-tinygarden/create_ad_post.py " >> auto-cron
echo "0 2,6,10,14,18,22 * * * cd /root/autopost-tiny/ && python3 create_ad_post.py >> create_ad_post_tiny.log 2>&1 " >> auto-cron
#install new cron file
crontab auto-cron
rm auto-cron
