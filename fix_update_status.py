with open('C:/Users/garvi/OneDrive/Documents/Projects/Hire-Edge-V2/backend/app.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Fix update_status body - remove freemium logic
old_update_body = """        is_truncated_emit = False
        try:
            with app.app_context():
                job_db = Job.query.filter_by(id=job_id).first()
                user = User.query.filter_by(id=user_id).first()
                if job_db:
                    job_db.status = status_str
                    job_db.progress = progress_val
                    job_db.current_message = msg_str
                    if results_dict is not None: job_db.results_json = json.dumps(results_dict)
                    if report_str is not None: job_db.report_content = report_str
                    if is_truncated_val: job_db.is_truncated = True
                    
                    # Increment free use ONLY on successful completion!
                    if inc_analyses_used and user and user.subscription_tier == 'free':
                        user.free_analyses_used += 1
                        
                    if status_str == 'complete':
                        job_db.analysis_number = Job.query.filter_by(user_id=user_id).count()
                        job_db.user_tier_at_time = user.subscription_tier if user else 'free'
                    
                    is_truncated_emit = bool(job_db.is_truncated)
                    db.session.commit()
                else:
                    is_truncated_emit = is_truncated_val
        except Exception as e:
            logging.error(f"[update_status] DB commit failed for {job_id}: {e}\\n{traceback.format_exc()}")
            try:
                with app.app_context():
                    db.session.rollback()
            except Exception:
                pass
            is_truncated_emit = is_truncated_val
            
        # Emit SocketIO update — never let emit crash the job (threading mode)
        try:
            socketio.emit('job_status', {
                'id': job_id,
                'status': status_str,
                'progress': progress_val,
                'message': msg_str,
                'agents': job["agents"],
                'results': results_dict,
                'is_truncated': is_truncated_emit
            }, room=job_id)"""

new_update_body = """        try:
            with app.app_context():
                job_db = Job.query.filter_by(id=job_id).first()
                if job_db:
                    job_db.status = status_str
                    job_db.progress = progress_val
                    job_db.current_message = msg_str
                    if results_dict is not None: job_db.results_json = json.dumps(results_dict)
                    if report_str is not None: job_db.report_content = report_str
                    
                    if status_str == 'complete':
                        job_db.analysis_number = Job.query.filter_by(user_id=user_id).count()
                    
                    db.session.commit()
        except Exception as e:
            logging.error(f"[update_status] DB commit failed for {job_id}: {e}\\n{traceback.format_exc()}")
            try:
                with app.app_context():
                    db.session.rollback()
            except Exception:
                pass
            
        # Emit SocketIO update — never let emit crash the job (threading mode)
        try:
            socketio.emit('job_status', {
                'id': job_id,
                'status': status_str,
                'progress': progress_val,
                'message': msg_str,
                'agents': job["agents"],
                'results': results_dict
            }, room=job_id)"""

if old_update_body in content:
    content = content.replace(old_update_body, new_update_body)
    print("Fixed update_status body")
else:
    print("update_status body not found!")
    # Debug: find the function
    idx = content.find("def update_status")
    if idx >= 0:
        print("Found at:", idx)
        print(content[idx:idx+500])

# Write back
with open('C:/Users/garvi/OneDrive/Documents/Projects/Hire-Edge-V2/backend/app.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("Done!")