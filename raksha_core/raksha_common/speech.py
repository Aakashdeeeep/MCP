"""Hindi text -> Amazon Polly (Kajal, neural, hi-IN) -> MP3 in S3 -> presigned URL."""
import os

import boto3
from botocore.config import Config

REGION = os.environ.get("AWS_REGION", "ap-south-1")  # TODO: confirm deploy region
AUDIO_BUCKET = os.environ.get("AUDIO_BUCKET", "raksha-audio-bucket-TODO")
VOICE_ID = "Kajal"  # bilingual hi-IN / en-IN neural voice, handles Hinglish
URL_EXPIRY_SECONDS = 3600

polly = boto3.client("polly")
# Regional endpoint + SigV4 so presigned URLs work right after the bucket is created
s3 = boto3.client(
    "s3",
    region_name=REGION,
    endpoint_url=f"https://s3.{REGION}.amazonaws.com",
    config=Config(signature_version="s3v4"),
)


def presign(key):
    return s3.generate_presigned_url(
        "get_object", Params={"Bucket": AUDIO_BUCKET, "Key": key}, ExpiresIn=URL_EXPIRY_SECONDS
    )


def speak_to_s3(text, key):
    audio = polly.synthesize_speech(
        Text=text, OutputFormat="mp3", VoiceId=VOICE_ID, LanguageCode="hi-IN", Engine="neural"
    )
    s3.put_object(Bucket=AUDIO_BUCKET, Key=key, Body=audio["AudioStream"].read(), ContentType="audio/mpeg")
    return presign(key)
