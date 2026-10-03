# Privacy

Raksha is a hackathon project. It is self-hosted: every record lives in the operator's own AWS
account (DynamoDB in the region they deploy to), and nothing is sent to the authors.

- **What is stored:** medicine doses and health readings the elder logs, family messages, alerts,
  pending approval requests, and a feed of safety decisions. OAuth codes and tokens are stored only
  as SHA-256 hashes, and they expire automatically (DynamoDB TTL).
- **Who sees it:** the family members who hold the family passcode, and the linked Alexa account.
- **Third parties:** Amazon Bedrock (scam checks, if enabled), Amazon SNS (family email), and
  optionally Twilio WhatsApp, Google Maps, OpenWeatherMap, NewsAPI or Razorpay *test mode*, but
  only when the operator configures their keys.
- **Deleting data:** delete the CloudFormation stack, which removes every table.
