import streamlit as st
import pandas as pd
import sqlite3
import datetime
import time
import hashlib
import pytz # NEW LIBRARY FOR TIMEZONES

# --- CONFIGURATION ---
DB_FILE = "exam_system.db"
st.set_page_config(page_title="Online Exam Portal", layout="wide")

# Define India Timezone
IST = pytz.timezone('Asia/Kolkata')

# --- DATABASE ENGINE ---
def run_query(query, params=(), fetch=False):
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    c = conn.cursor()
    c.execute(query, params)
    if fetch:
        data = c.fetchall()
        conn.close()
        return data
    conn.commit()
    conn.close()

def init_db():
    run_query('''CREATE TABLE IF NOT EXISTS users 
                 (username TEXT PRIMARY KEY, password TEXT, role TEXT, score REAL)''')
    run_query('''CREATE TABLE IF NOT EXISTS config 
                 (key TEXT PRIMARY KEY, value TEXT)''')
    run_query('''CREATE TABLE IF NOT EXISTS questions 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                  question TEXT, opt1 TEXT, opt2 TEXT, opt3 TEXT, opt4 TEXT, correct_opt TEXT)''')
    
    # Create Admin
    if not run_query("SELECT * FROM users WHERE role='admin'", fetch=True):
        run_query("INSERT INTO users VALUES (?, ?, ?, ?)", 
                  ('admin', hashlib.sha256(b'admin123').hexdigest(), 'admin', 0))

# --- HELPER FUNCTIONS ---
def make_hashes(password):
    return hashlib.sha256(str.encode(password)).hexdigest()

def get_current_time():
    """Returns current time in IST"""
    return datetime.datetime.now(IST)

def calculate_and_submit(user):
    neg_mark = run_query("SELECT value FROM config WHERE key='neg_marking'", fetch=True)
    penalty = run_query("SELECT value FROM config WHERE key='penalty'", fetch=True)
    
    is_neg = (neg_mark[0][0] == '1') if neg_mark else False
    pen_val = float(penalty[0][0]) if penalty else 0.0

    questions = run_query("SELECT * FROM questions", fetch=True)
    user_ans = st.session_state.get('user_answers', {})
    
    score = 0
    total = len(questions)
    
    for q in questions:
        qid = q[0]
        correct = q[6]
        selected = user_ans.get(qid, None)
        
        if selected == correct:
            score += 1
        elif selected is not None and is_neg:
            score -= pen_val
            
    final_percent = (score / total) * 100 if total > 0 else 0
    run_query("UPDATE users SET score=? WHERE username=?", (final_percent, user))
    return final_percent

# --- PAGES ---

def page_login():
    st.header("Exam Login")
    tab1, tab2 = st.tabs(["Login", "Sign Up"])
    
    with tab1:
        user = st.text_input("Username")
        pwd = st.text_input("Password", type="password")
        if st.button("Login"):
            hashed = make_hashes(pwd)
            data = run_query("SELECT * FROM users WHERE username=? AND password=?", (user, hashed), fetch=True)
            if data:
                st.session_state['user'] = data[0][0]
                st.session_state['role'] = data[0][2]
                st.rerun()
            else:
                st.error("Invalid credentials")

    with tab2:
        new_u = st.text_input("New Username")
        new_p = st.text_input("New Password", type="password")
        if st.button("Create Account"):
            if run_query("SELECT * FROM users WHERE username=?", (new_u,), fetch=True):
                st.error("User exists")
            else:
                run_query("INSERT INTO users VALUES (?, ?, ?, ?)", 
                          (new_u, make_hashes(new_p), 'student', -999))
                st.success("Account created! Please Login.")

def page_admin():
    st.title("Admin Panel")
    
    # DEBUG: Show current time to Admin to be sure
    now_ist = get_current_time()
    st.info(f"Current Server Time (IST): {now_ist.strftime('%Y-%m-%d %H:%M:%S')}")

    st.subheader("1. Exam Settings")
    defaults = {}
    for k in ['start_time', 'duration', 'neg_marking', 'penalty', 'show_result']:
        res = run_query(f"SELECT value FROM config WHERE key='{k}'", fetch=True)
        defaults[k] = res[0][0] if res else None

    with st.form("settings_form"):
        c1, c2 = st.columns(2)
        # Default to current IST time
        exam_d = c1.date_input("Exam Date", value=now_ist.date())
        exam_t = c2.time_input("Start Time", value=now_ist.time())
        dur = st.number_input("Duration (minutes)", value=30, min_value=1)
        
        st.markdown("**Scoring Rules**")
        ena_neg = st.checkbox("Enable Negative Marking?", value=(defaults['neg_marking']=='1'))
        pen_amt = st.number_input("Penalty", value=0.25, step=0.05)
        show_res = st.checkbox("Show result immediately?", value=True)
        
        if st.form_submit_button("Save Settings"):
            # Combine Date and Time and attach IST timezone info
            dt_naive = datetime.datetime.combine(exam_d, exam_t)
            dt_aware = IST.localize(dt_naive)
            
            run_query("INSERT OR REPLACE INTO config VALUES ('start_time', ?)", (dt_aware.isoformat(),))
            run_query("INSERT OR REPLACE INTO config VALUES ('duration', ?)", (str(dur),))
            run_query("INSERT OR REPLACE INTO config VALUES ('neg_marking', ?)", ('1' if ena_neg else '0',))
            run_query("INSERT OR REPLACE INTO config VALUES ('penalty', ?)", (str(pen_amt),))
            run_query("INSERT OR REPLACE INTO config VALUES ('show_result', ?)", ('1' if show_res else '0',))
            st.success("Settings Saved!")

    st.subheader("2. Upload Questions")
    up_file = st.file_uploader("Upload CSV", type='csv')
    if up_file and st.button("Process CSV"):
        df = pd.read_csv(up_file)
        run_query("DELETE FROM questions") 
        for _, row in df.iterrows():
            run_query("INSERT INTO questions (question, opt1, opt2, opt3, opt4, correct_opt) VALUES (?,?,?,?,?,?)",
                      (row['question'], row['opt1'], row['opt2'], row['opt3'], row['opt4'], row['correct_opt']))
        st.success("Questions uploaded successfully")

    st.subheader("3. Student Results")
    res = run_query("SELECT username, score FROM users WHERE role='student'", fetch=True)
    if res:
        df = pd.DataFrame(res, columns=['Student', 'Score %'])
        st.dataframe(df[df['Score %'] != -999]) 
        csv = df.to_csv(index=False).encode('utf-8')
        st.download_button("Download CSV", csv, "results.csv", "text/csv")

def page_exam():
    user = st.session_state['user']
    
    # Check if submitted
    my_score = run_query("SELECT score FROM users WHERE username=?", (user,), fetch=True)[0][0]
    if my_score != -999:
        st.info("Exam Submitted.")
        show_res = run_query("SELECT value FROM config WHERE key='show_result'", fetch=True)
        if show_res and show_res[0][0] == '1':
            st.metric("Your Score", f"{my_score:.2f} %")
        else:
            st.write("Results hidden.")
        return

    # Check Schedule
    start_str = run_query("SELECT value FROM config WHERE key='start_time'", fetch=True)
    dur_str = run_query("SELECT value FROM config WHERE key='duration'", fetch=True)
    
    if not start_str or not dur_str:
        st.warning("Exam not scheduled.")
        return

    # Parse Time (Handle IST)
    start_dt = datetime.datetime.fromisoformat(start_str[0][0])
    end_dt = start_dt + datetime.timedelta(minutes=int(dur_str[0][0]))
    now = get_current_time()

    # Time Logic
    if now < start_dt:
        st.warning(f"Exam starts at: {start_dt.strftime('%H:%M:%S')}")
        st.info(f"Current Time: {now.strftime('%H:%M:%S')}")
        time.sleep(2) # Refresh faster
        st.rerun()
        return

    if now > end_dt:
        st.error("Time is up! Auto-submitting...")
        calculate_and_submit(user)
        st.rerun()
        return

    # EXAM INTERFACE
    left_sec = (end_dt - now).total_seconds()
    st.sidebar.metric("Time Left", f"{int(left_sec//60)}:{int(left_sec%60):02d}")
    
    questions = run_query("SELECT * FROM questions", fetch=True)
    if 'user_answers' not in st.session_state:
        st.session_state['user_answers'] = {}

    st.header("Final Exam")
    for q in questions:
        qid = q[0]
        opts = [q[2], q[3], q[4], q[5]]
        prev = st.session_state['user_answers'].get(qid, None)
        idx = opts.index(prev) if prev else None
        val = st.radio(f"**{q[1]}**", opts, index=idx, key=qid)
        st.session_state['user_answers'][qid] = val
        st.write("---")

    if st.button("Submit Final Answers"):
        calculate_and_submit(user)
        st.rerun()
    
    time.sleep(1)
    st.rerun()

# --- MAIN ---
init_db()

if 'user' not in st.session_state:
    page_login()
else:
    st.sidebar.write(f"User: {st.session_state['user']}")
    if st.sidebar.button("Logout"):
        del st.session_state['user']
        st.rerun()
        
    if st.session_state['role'] == 'admin':
        page_admin()
    else:
        page_exam()
