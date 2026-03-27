import os
import boto3
from datetime import datetime, timezone, timedelta

table     = boto3.resource('dynamodb').Table(os.environ['TABLE_NAME'])
ses       = boto3.client('ses', region_name='eu-central-1')
THRESHOLD = timedelta(minutes=int(os.environ.get('THRESHOLD_MINUTES', '15')))
ALERT_TO  = os.environ['ALERT_TO']
ALERT_FROM = os.environ['ALERT_FROM']


def lambda_handler(event, context):
    item = table.get_item(Key={'source': 'lasvegas'}).get('Item')
    if not item:
        _alert('No heartbeat record found for lasvegas.')
        return
    age = datetime.now(timezone.utc) - datetime.fromisoformat(item['timestamp'])
    if age > THRESHOLD:
        _alert(f'No heartbeat for {int(age.total_seconds() // 60)} minutes.')


def _alert(detail):
    ses.send_email(
        Source=ALERT_FROM,
        Destination={'ToAddresses': [ALERT_TO]},
        Message={
            'Subject': {'Data': 'Alert: Bitcoin node not reachable'},
            'Body': {'Text': {'Data': f'Bitcoin node (lasvegas) is down.\n\n{detail}'}},
        },
    )
