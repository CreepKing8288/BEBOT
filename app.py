import os
from flask import Flask, render_template
from pymongo import MongoClient

app = Flask(__name__)

# MongoDB Setup (Same as your bot)
MONGO_URI = os.getenv("MONGODB_URI")
client = MongoClient(MONGO_URI)
db = client.get_database(os.getenv("MONGO_DB"))
# The collection where user swear counts are stored
counts_coll = db[os.getenv("MONGO_COLLECTION")]

@app.route('/')
def dashboard():
    # Fetch all user data from MongoDB
    cursor = counts_coll.find({})
    leaderboard = []
    
    for doc in cursor:
        uid = doc.get("_id")
        counts = doc.get("counts", {})
        total = sum(counts.values())
        if total > 0:
            # Sort individual words for this user
            sorted_words = sorted(counts.items(), key=lambda x: x[1], reverse=True)
            leaderboard.append({
                "uid": uid,
                "total": total,
                "top_word": sorted_words[0][0] if sorted_words else "N/A"
            })

    # Sort leaderboard by total count descending
    leaderboard = sorted(leaderboard, key=lambda x: x['total'], reverse=True)

    return render_template('index.html', leaderboard=leaderboard)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)