#!/bin/bash
# Setup daily report cron job for AI customer service statistics
# This script should be run on the server (120.26.199.225)

# Configuration
PUSHPLUS_TOKEN="${1:-}"  # Pass token as first argument
REPORT_TIME="${2:-08:00}"  # Default 8:00 AM, format HH:MM

if [ -z "$PUSHPLUS_TOKEN" ]; then
    echo "Usage: $0 <PUSHPLUS_TOKEN> [REPORT_TIME]"
    echo "Example: $0 abc123token 08:00"
    echo ""
    echo "Get your token from: https://www.pushplus.plus/"
    exit 1
fi

# Parse time
HOUR=$(echo $REPORT_TIME | cut -d: -f1)
MINUTE=$(echo $REPORT_TIME | cut -d: -f2)

echo "Setting up daily report..."
echo "  Token: ${PUSHPLUS_TOKEN:0:6}***"
echo "  Time: $HOUR:$MINUTE"

# Add token to .env file
ENV_FILE="/opt/ai-kefu/.env"
if grep -q "PUSHPLUS_TOKEN" $ENV_FILE 2>/dev/null; then
    sed -i "s/PUSHPLUS_TOKEN=.*/PUSHPLUS_TOKEN=$PUSHPLUS_TOKEN/" $ENV_FILE
else
    echo "PUSHPLUS_TOKEN=$PUSHPLUS_TOKEN" >> $ENV_FILE
fi
echo "  Token saved to $ENV_FILE"

# Create cron job
CRON_CMD="$MINUTE $HOUR * * * cd /opt/ai-kefu && docker compose exec -T backend python manage.py daily_report >> /var/log/ai-kefu-report.log 2>&1"

# Remove existing daily_report cron if exists
crontab -l 2>/dev/null | grep -v "daily_report" | crontab -

# Add new cron job
(crontab -l 2>/dev/null; echo "$CRON_CMD") | crontab -

echo "  Cron job added for daily report at $HOUR:$MINUTE"

# Also add weekly report on Monday
WEEKLY_CMD="0 9 * * 1 cd /opt/ai-kefu && docker compose exec -T backend python manage.py daily_report --period weekly >> /var/log/ai-kefu-report.log 2>&1"
(crontab -l 2>/dev/null; echo "$WEEKLY_CMD") | crontab -
echo "  Weekly report added for Monday 9:00 AM"

# Verify
echo ""
echo "Current cron jobs:"
crontab -l | grep -E "(daily_report|ai-kefu)"

echo ""
echo "Setup complete! Test with:"
echo "  cd /opt/ai-kefu && docker compose exec backend python manage.py daily_report --dry-run"
