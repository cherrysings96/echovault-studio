import sqlite3
import csv
import io
from flask import Flask, render_template, request, redirect, url_for, flash, Response

app = Flask(__name__)
app.secret_key = "echovault_secret_key_dev"
DB_NAME = "studio.db"


def get_db_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()

    # Table 1: Vocal Projects (Songs/Covers)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            original_artist TEXT NOT NULL,
            original_key TEXT NOT NULL,
            transposed_key TEXT NOT NULL,
            bpm INTEGER NOT NULL,
            status TEXT DEFAULT 'Recording',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Table 2: Recording Takes
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS takes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            take_number INTEGER NOT NULL,
            section TEXT NOT NULL,
            mic_chain TEXT NOT NULL,
            pitch_score INTEGER NOT NULL,
            timing_score INTEGER NOT NULL,
            vibe_score INTEGER NOT NULL,
            composite_score REAL NOT NULL,
            vocal_strain TEXT NOT NULL,
            notes TEXT,
            recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (project_id) REFERENCES projects (id) ON DELETE CASCADE
        )
    """)

    # Table 3: YouTube Reach & Algorithm Telemetry
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS youtube_trends (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            trend_tier TEXT NOT NULL,
            arrangement_style TEXT NOT NULL,
            competition_level TEXT NOT NULL,
            estimated_impressions INTEGER NOT NULL,
            reach_probability REAL NOT NULL,
            predicted_ctr REAL NOT NULL,
            recommended_tags TEXT,
            analyzed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (project_id) REFERENCES projects (id) ON DELETE CASCADE
        )
    """)

    # Seed sample project and take data if empty
    cursor.execute("SELECT COUNT(*) FROM projects")
    if cursor.fetchone()[0] == 0:
        cursor.execute("""
            INSERT INTO projects (title, original_artist, original_key, transposed_key, bpm, status)
            VALUES 
            ('Rolling in the Deep (Acoustic Cover)', 'Adele', 'C Minor', 'B Minor (-1)', 105, 'Mixing'),
            ('Valerie (Soul Arrangement)', 'Amy Winehouse', 'Eb Major', 'Eb Major (0)', 106, 'Recording'),
            ('Drivers License (Piano Ballad)', 'Olivia Rodrigo', 'Bb Major', 'A Major (-1)', 72, 'Mastered')
        """)

        cursor.execute("""
            INSERT INTO takes (project_id, take_number, section, mic_chain, pitch_score, timing_score, vibe_score, composite_score, vocal_strain, notes)
            VALUES 
            (1, 1, 'Chorus High Belt', 'Shure SM7B + Cloudlifter (Gain 60%)', 8, 9, 9, 86.5, 'Low', 'Clean chest-mix transition on the high C.'),
            (1, 2, 'Bridge Stacked Harmony', 'AT2020 Condenser (Pop Filter 4 in)', 9, 8, 10, 91.0, 'Moderate', 'Slightly breathy tone works well for the backing track.'),
            (2, 1, 'Verse 1 Groove', 'Shure SM7B (Flat EQ)', 7, 8, 8, 76.5, 'Low', 'Rushed the second bar slightly; good warmth.')
        """)

    # Seed initial trend reach telemetry if empty
    cursor.execute("SELECT COUNT(*) FROM youtube_trends")
    if cursor.fetchone()[0] == 0:
        cursor.execute("""
            INSERT INTO youtube_trends (project_id, trend_tier, arrangement_style, competition_level, estimated_impressions, reach_probability, predicted_ctr, recommended_tags)
            VALUES 
            (1, 'Evergreen High Velocity', 'Stripped Acoustic / Piano', 'High', 38500, 78.4, 8.2, '#adele #acousticcover #vocalcover #livesession'),
            (3, 'Viral Surge', 'Cinematic Orchestral', 'Medium', 62000, 89.1, 10.4, '#oliviarodrigo #driverslicense #ballad #singersongwriter')
        """)

    conn.commit()
    conn.close()


def calculate_readiness(pitch, timing, vibe):
    """Weighted studio formula: Vibe (40%), Pitch (35%), Timing (25%)."""
    weighted = (pitch * 0.35) + (timing * 0.25) + (vibe * 0.40)
    return round(weighted * 10, 1)


def calculate_youtube_reach(trend_tier, arrangement_style, competition_level, avg_readiness):
    """
    Computes algorithmic reach probability based on:
    - Trend velocity weight (0-35)
    - Arrangement novelty / audience retention potential (0-25)
    - Saturation resistance / competition penalty (0-20)
    - Vocal performance baseline readiness (0-20)
    """
    trend_weights = {
        "Viral Surge": 35,
        "Trending Breakout": 30,
        "Evergreen High Velocity": 25,
        "Niche / Cult Classic": 18
    }
    arrangement_weights = {
        "Stripped Acoustic / Piano": 23,
        "Cinematic Orchestral": 25,
        "Upbeat Indie Pop": 21,
        "Lo-Fi R&B Re-harmonization": 24,
        "Raw 1-Take Live Vocal": 22
    }
    competition_penalties = {
        "Low (Undersaturated Cover Niche)": 20,
        "Medium": 14,
        "High": 9
    }

    trend_score = trend_weights.get(trend_tier, 22)
    arr_score = arrangement_weights.get(arrangement_style, 20)
    comp_score = competition_penalties.get(competition_level, 12)
    vocal_contribution = (avg_readiness / 100.0) * 20.0

    total_probability = round(min(trend_score + arr_score + comp_score + vocal_contribution, 98.5), 1)

    # Base impressions mapping based on probability & competition
    base_impressions = int(total_probability * 580)
    if competition_level.startswith("Low"):
        base_impressions += 12000
    elif competition_level == "High":
        base_impressions = int(base_impressions * 0.85)

    predicted_ctr = round(min(max((total_probability / 10.0) + 1.2, 3.5), 14.2), 1)

    return total_probability, base_impressions, predicted_ctr


@app.route("/")
def index():
    status_filter = request.args.get("status", "All")
    search_query = request.args.get("q", "").strip()

    conn = get_db_connection()

    base_query = """
        SELECT 
            p.*,
            COUNT(t.id) AS total_takes,
            ROUND(AVG(t.composite_score), 1) AS avg_readiness,
            MAX(t.composite_score) AS best_take_score
        FROM projects p
        LEFT JOIN takes t ON p.id = t.project_id
        WHERE 1=1
    """
    params = []

    if status_filter and status_filter != "All":
        base_query += " AND p.status = ?"
        params.append(status_filter)

    if search_query:
        base_query += " AND (p.title LIKE ? OR p.original_artist LIKE ?)"
        params.extend([f"%{search_query}%", f"%{search_query}%"])

    base_query += " GROUP BY p.id ORDER BY p.created_at DESC"
    projects = conn.execute(base_query, params).fetchall()

    all_projects = conn.execute("SELECT id, title, transposed_key FROM projects ORDER BY title ASC").fetchall()

    recent_takes = conn.execute("""
        SELECT t.*, p.title AS project_title, p.transposed_key
        FROM takes t
        JOIN projects p ON t.project_id = p.id
        ORDER BY t.recorded_at DESC
        LIMIT 15
    """).fetchall()

    stats = conn.execute("""
        SELECT 
            (SELECT COUNT(*) FROM projects) AS project_count,
            COUNT(*) AS total_takes,
            ROUND(AVG(composite_score), 1) AS studio_avg_score,
            SUM(CASE WHEN vocal_strain = 'High' THEN 1 ELSE 0 END) AS high_strain_count
        FROM takes
    """).fetchone()

    conn.close()
    return render_template(
        "index.html",
        projects=projects,
        all_projects=all_projects,
        takes=recent_takes,
        stats=stats,
        current_status=status_filter,
        search_query=search_query
    )


@app.route("/youtube-reach")
def youtube_reach():
    conn = get_db_connection()

    # Query trend forecasts with joined project info and dynamic readiness
    reach_analyses = conn.execute("""
        SELECT 
            y.*,
            p.title AS project_title,
            p.original_artist,
            p.transposed_key,
            ROUND(AVG(t.composite_score), 1) AS live_readiness
        FROM youtube_trends y
        JOIN projects p ON y.project_id = p.id
        LEFT JOIN takes t ON p.id = t.project_id
        GROUP BY y.id
        ORDER BY y.analyzed_at DESC
    """).fetchall()

    # Query all active projects for the run analysis form
    projects = conn.execute("""
        SELECT 
            p.id, 
            p.title, 
            p.original_artist,
            COALESCE(ROUND(AVG(t.composite_score), 1), 75.0) AS avg_readiness
        FROM projects p
        LEFT JOIN takes t ON p.id = t.project_id
        GROUP BY p.id
        ORDER BY p.title ASC
    """).fetchall()

    # Aggregated forecast metrics
    reach_stats = conn.execute("""
        SELECT 
            COUNT(*) AS total_forecasts,
            ROUND(AVG(reach_probability), 1) AS avg_probability,
            SUM(estimated_impressions) AS total_projected_impressions,
            ROUND(AVG(predicted_ctr), 1) AS avg_projected_ctr
        FROM youtube_trends
    """).fetchone()

    conn.close()
    return render_template("youtube_reach.html", analyses=reach_analyses, projects=projects, stats=reach_stats)


@app.route("/add_forecast", methods=["POST"])
def add_forecast():
    project_id = request.form.get("project_id", type=int)
    trend_tier = request.form.get("trend_tier")
    arrangement_style = request.form.get("arrangement_style")
    competition_level = request.form.get("competition_level")
    recommended_tags = request.form.get("recommended_tags", "").strip()

    conn = get_db_connection()
    # Fetch live performance readiness to influence forecast
    take_stats = conn.execute("""
        SELECT COALESCE(ROUND(AVG(composite_score), 1), 78.0) 
        FROM takes 
        WHERE project_id = ?
    """, (project_id,)).fetchone()
    avg_readiness = take_stats[0]

    probability, impressions, predicted_ctr = calculate_youtube_reach(
        trend_tier, arrangement_style, competition_level, avg_readiness
    )

    if not recommended_tags:
        recommended_tags = f"#vocalcover #shorts #trendingmusic #{trend_tier.split()[0].lower()}"

    conn.execute("""
        INSERT INTO youtube_trends 
        (project_id, trend_tier, arrangement_style, competition_level, estimated_impressions, reach_probability, predicted_ctr, recommended_tags)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (project_id, trend_tier, arrangement_style, competition_level, impressions, probability, predicted_ctr, recommended_tags))
    conn.commit()
    conn.close()

    flash(f"Algorithmic forecast generated! Reach Probability: {probability}%", "success")
    return redirect(url_for("youtube_reach"))


@app.route("/delete_forecast/<int:forecast_id>", methods=["POST"])
def delete_forecast(forecast_id):
    conn = get_db_connection()
    conn.execute("DELETE FROM youtube_trends WHERE id = ?", (forecast_id,))
    conn.commit()
    conn.close()
    flash("Forecast model removed.", "warning")
    return redirect(url_for("youtube_reach"))


@app.route("/add_project", methods=["POST"])
def add_project():
    title = request.form.get("title")
    original_artist = request.form.get("original_artist")
    original_key = request.form.get("original_key")
    transposed_key = request.form.get("transposed_key")
    bpm = request.form.get("bpm", type=int)
    status = request.form.get("status")

    conn = get_db_connection()
    conn.execute("""
        INSERT INTO projects (title, original_artist, original_key, transposed_key, bpm, status)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (title, original_artist, original_key, transposed_key, bpm, status))
    conn.commit()
    conn.close()

    flash(f"Added '{title}' to active studio sessions!", "success")
    return redirect(url_for("index"))


@app.route("/add_take", methods=["POST"])
def add_take():
    project_id = request.form.get("project_id", type=int)
    section = request.form.get("section")
    mic_chain = request.form.get("mic_chain")
    pitch_score = request.form.get("pitch_score", type=int)
    timing_score = request.form.get("timing_score", type=int)
    vibe_score = request.form.get("vibe_score", type=int)
    vocal_strain = request.form.get("vocal_strain")
    notes = request.form.get("notes")

    composite_score = calculate_readiness(pitch_score, timing_score, vibe_score)

    conn = get_db_connection()
    cur = conn.execute("SELECT COALESCE(MAX(take_number), 0) + 1 FROM takes WHERE project_id = ?", (project_id,))
    next_take_num = cur.fetchone()[0]

    conn.execute("""
        INSERT INTO takes 
        (project_id, take_number, section, mic_chain, pitch_score, timing_score, vibe_score, composite_score, vocal_strain, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (project_id, next_take_num, section, mic_chain, pitch_score, timing_score, vibe_score, composite_score, vocal_strain, notes))
    conn.commit()
    conn.close()

    flash(f"Logged Take #{next_take_num} — Mix-Readiness Score: {composite_score}%", "info")
    return redirect(url_for("index"))


@app.route("/update_status/<int:project_id>", methods=["POST"])
def update_status(project_id):
    new_status = request.form.get("status")
    conn = get_db_connection()
    conn.execute("UPDATE projects SET status = ? WHERE id = ?", (new_status, project_id))
    conn.commit()
    conn.close()
    flash(f"Updated project stage to '{new_status}'.", "info")
    return redirect(url_for("index"))


@app.route("/delete_project/<int:project_id>", methods=["POST"])
def delete_project(project_id):
    conn = get_db_connection()
    conn.execute("DELETE FROM takes WHERE project_id = ?", (project_id,))
    conn.execute("DELETE FROM youtube_trends WHERE project_id = ?", (project_id,))
    conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
    conn.commit()
    conn.close()
    flash("Project removed from studio vault.", "warning")
    return redirect(url_for("index"))


@app.route("/delete_take/<int:take_id>", methods=["POST"])
def delete_take(take_id):
    conn = get_db_connection()
    conn.execute("DELETE FROM takes WHERE id = ?", (take_id,))
    conn.commit()
    conn.close()
    flash("Vocal take deleted.", "warning")
    return redirect(url_for("index"))


@app.route("/export_csv")
def export_csv():
    conn = get_db_connection()
    rows = conn.execute("""
        SELECT 
            p.title AS song_title,
            p.original_artist,
            p.original_key,
            p.transposed_key,
            p.bpm,
            p.status,
            t.take_number,
            t.section,
            t.mic_chain,
            t.pitch_score,
            t.timing_score,
            t.vibe_score,
            t.composite_score,
            t.vocal_strain,
            t.notes,
            t.recorded_at
        FROM takes t
        JOIN projects p ON t.project_id = p.id
        ORDER BY p.title ASC, t.take_number ASC
    """).fetchall()
    conn.close()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Song Title", "Original Artist", "Original Key", "Studio Vocal Key", "BPM", "Stage",
        "Take #", "Section", "Mic & Preamp Chain", "Pitch (1-10)", "Timing (1-10)",
        "Vibe (1-10)", "Mix-Readiness (%)", "Vocal Strain", "Producer Notes", "Recorded Timestamp"
    ])

    for row in rows:
        writer.writerow(list(row))

    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment;filename=echovault_session_report.csv"}
    )


# Automatically initialize SQLite database on startup
init_db()

if __name__ == "__main__":
    app.run(debug=True)