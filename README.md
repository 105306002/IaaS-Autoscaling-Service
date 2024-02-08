# IaaS Cloud Computing
Documentation for Running App-Tier and Web-Tier Flask Servers

1. Prerequisites:
Make sure you have Python3 and Flask installed. If not, install them:
bash
Copy code
sudo apt update
sudo apt install python3 python3-pip
pip3 install Flask
AWS EC2 instance (for the App-Tier).
Local machine or another EC2 instance (for the Web-Tier).
2. Setting up App-Tier Flask Server:
SSH into the EC2 instance:
bash
Copy code
ssh -i "path_to_your_private_key.pem" ubuntu@your_ec2_ip_address
Navigate to the directory where your app.py for App-Tier is located:
bash
Copy code
cd /path_to_app_tier_directory/
Run the Flask server:
bash
Copy code
python3 app.py
The App-Tier Flask server should now be running on http://0.0.0.0:5001/process_image.
3. Setting up Web-Tier Flask Server:
On your local machine or another EC2 instance, navigate to the directory where your app.py for Web-Tier is located:
bash
Copy code
cd /path_to_web_tier_directory/
Run the Flask server:
bash
Copy code
python3 app.py
The Web-Tier Flask server should now be running on http://0.0.0.0:5000/send_image.
4. Testing the Setup:
From a separate terminal on your local machine, test the Web-Tier Flask server by sending an image for processing:
bash
Copy code
curl -X POST -F "file=@path_to_image_on_your_machine" http://0.0.0.0:5000/send_image
The Web-Tier server will forward the image to the App-Tier server, process it, and then return the result.
Note: Ensure that security groups and firewalls are appropriately configured to allow incoming traffic on the required ports for both servers (5000 for Web-Tier and 5001 for App-Tier).
