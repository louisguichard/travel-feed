import os
import json
import datetime
import uuid
import locale
from flask import Flask, render_template, request, redirect, url_for
from google.cloud import storage

# Set locale to French for date formatting
try:
    locale.setlocale(locale.LC_TIME, 'fr_FR.UTF-8')
except locale.Error:
    locale.setlocale(locale.LC_TIME, 'French')


app = Flask(__name__)

# --- Configuration ---
BUCKET_NAME = 'travel-feed'
DB_FILE = 'db.json'
# ---

# Initialize Google Cloud Storage client
# This will automatically use your local authentication
# or the service account on Cloud Run.
storage_client = storage.Client()
bucket = storage_client.bucket(BUCKET_NAME)


def get_posts():
    """Reads and returns all posts from the JSON database."""
    if not os.path.exists(DB_FILE):
        return []
    with open(DB_FILE, 'r') as f:
        posts_data = json.load(f)
        # Convert date strings back to datetime objects for sorting
        for post in posts_data:
            post['date'] = datetime.datetime.strptime(post['date'], '%Y-%m-%d').date()
    # Sort posts in anti-chronological order (newest first)
    return sorted(posts_data, key=lambda x: x['date'], reverse=True)


def save_posts(posts):
    """Saves the list of posts to the JSON database."""
    with open(DB_FILE, 'w') as f:
        # Convert date objects to strings for JSON serialization
        json.dump(posts, f, indent=4, default=str)


@app.route("/")
def index():
    posts = get_posts()
    return render_template("index.html", posts=posts)


@app.route("/add", methods=['GET', 'POST'])
def add():
    if request.method == 'POST':
        media_urls = []
        files = request.files.getlist('media')

        for file in files:
            if file.filename:
                # Generate a unique filename
                filename = f"{uuid.uuid4()}{os.path.splitext(file.filename)[1]}"
                blob = bucket.blob(filename)

                # Upload the file to GCS
                blob.upload_from_file(file.stream, content_type=file.content_type)
                
                # The bucket needs to be publicly readable.
                # The make_public() call is not needed and will fail
                # on buckets with uniform access control.
                media_urls.append(blob.public_url)

        new_post = {
            'id': str(uuid.uuid4()),
            'city': request.form.get('city'),
            'date': request.form.get('date'),
            'title': request.form.get('title'),
            'text': request.form.get('text'),
            'media': media_urls,
            'timestamp': datetime.datetime.utcnow().isoformat()
        }

        posts = get_posts()
        posts.append(new_post)
        save_posts(posts)

        return redirect(url_for('index'))

    return render_template("add.html")


if __name__ == "__main__":
    app.run(debug=True)
