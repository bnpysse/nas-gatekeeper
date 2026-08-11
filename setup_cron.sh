#!/bin/bash
set -e
echo "Setting up Cron..."
CRON_JOB="0 */2 * * * bash $(pwd)/run_crawler.sh"
(crontab -l 2>/dev/null | grep -F "run_crawler.sh") || (crontab -l 2>/dev/null; echo "$CRON_JOB") | crontab -
echo "Cron configured."

echo "Triggering fetcher..."
bash run_crawler.sh
