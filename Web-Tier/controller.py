import os
import io
import boto3
import logging
import traceback
from flask import Flask, request, jsonify
import sys
import requests
import argparse
import _thread
import time
import subprocess
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import as_completed
from flask_cors import CORS

region = "us-east-1"
request_queue_url = "https://sqs.us-east-1.amazonaws.com/580774365972/CSE546-Project1SendToAppTierQueue"
response_queue_url = "https://sqs.us-east-1.amazonaws.com/580774365972/CSE546-Project1SendToWebTierQueue"

# Initialize AWS clients for S3, SQS, EC2, CloudWatch and AutoScaling
s3 = boto3.client('s3', 
                  region_name = region
                  )  
sqs = boto3.client('sqs', 
                    region_name = region
                )  
ec2 = boto3.client('ec2', 
                   region_name = region
                  )
cloudwatch = boto3.client('cloudwatch',
                          region_name = region
                      )
autoscaling = boto3.client('autoscaling',
                           region_name = region
                           )

# Define S3 bucket names
input_bucket_name = 'cse546-project1inputbucket'
output_bucket_name = 'cse546-project1outputbucket'


app = Flask(__name__)
CORS(app)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@app.route('/send_image', methods=['POST'])
def upload_image_to_s3():
    print("Endpoint /send_image accessed.")
    try:
        # Get the uploaded image file from the request
        uploaded_file = request.files.get('myfile')
        if not uploaded_file:
            return jsonify({'error': 'Image file not provided'}), 400
        
        # Get the file name of the uploaded file
        file_name = uploaded_file.filename

        # Read the binary data of the image
        image_data = uploaded_file.read()

        image_data = io.BytesIO(image_data)
        
        # Upload the image data to S3
        s3.upload_fileobj(Fileobj=image_data, Bucket=input_bucket_name, Key=file_name)
        print('%s uploaded' % file_name)

        send_request_to_sqs(file_name)
        print("filename sent to SQS queue.")

        # pull the result from response sqs queue
        while True:
            response = sqs.receive_message(QueueUrl=response_queue_url, MaxNumberOfMessages=1)
            if 'Messages' in response:
                message = response['Messages'][0]
                receipt_handle = message['ReceiptHandle']
                sqs.delete_message(QueueUrl=response_queue_url, ReceiptHandle=receipt_handle)
                print('Received and deleted message: %s' % message)
                return (message['Body'])
            else:
                print('No messages in response queue.')
                time.sleep(1)

    except Exception as e:
        print("Error Traceback:")
        print(traceback.format_exc())  # Print the detailed traceback
        return jsonify({'error': 'An error occurred: ' + str(e)}), 500
    
# send file name to sqs
def send_request_to_sqs(image_filename):
    try:
        print(image_filename)
        response = sqs.send_message(
            QueueUrl=request_queue_url,
            MessageBody=image_filename
        )
        print("Message sent to SQS queue.")
        return response
    except Exception as e:   
        return jsonify({'error': 'An error occurred: ' + str(e)}), 500


metric_name = 'QueueDepth'
namespace = 'CustomMetrics'
queue_name = 'request-queue'



if __name__ == "__main__":
    app.run(debug=False, host='0.0.0.0', port=5000, threaded=True)
