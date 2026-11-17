with open('C:/Users/garvi/OneDrive/Documents/Projects/Hire-Edge-V2/backend/app.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Fix the run_job completion logic - remove truncation
old_completion = """        (REPORTS_FOLDER / f"{job_id}.txt").write_text(report, encoding="utf-8")
        job_results = {"a1":r1,"a2":r2,"a3":r3,"a4":r4,"a5":r5,"a6":r6}

        # Truncation logic (Phase 3)
        with app.app_context():
            user = User.query.filter_by(id=user_id).first()
            analysis_count = Job.query.filter_by(user_id=user_id).count()
            is_free_tier = user and user.subscription_tier == 'free'
            is_second_plus = analysis_count >= 2
            is_truncated = False
            results_to_save = job_results
            
            if is_free_tier and is_second_plus:
                results_to_save = truncate_agent_outputs(job_results, percentage=70)
                is_truncated = True

        update_status("complete", 6, "Analysis complete.", results_dict=results_to_save, report_str=report, is_truncated_val=is_truncated, inc_analyses_used=True)"""

new_completion = """        (REPORTS_FOLDER / f"{job_id}.txt").write_text(report, encoding="utf-8")
        job_results = {"a1":r1,"a2":r2,"a3":r3,"a4":r4,"a5":r5,"a6":r6}

        update_status("complete", 6, "Analysis complete.", results_dict=job_results, report_str=report)"""

if old_completion in content:
    content = content.replace(old_completion, new_completion)
    print("Fixed completion logic")
else:
    print("Completion logic not found!")

# 2. Fix update_status function definition
old_update_def = "    def update_status(status_str, progress_val, msg_str, results_dict=None, report_str=None, is_truncated_val=False, inc_analyses_used=False):"
new_update_def = "    def update_status(status_str, progress_val, msg_str, results_dict=None, report_str=None):"

if old_update_def in content:
    content = content.replace(old_update_def, new_update_def)
    print("Fixed update_status definition")
else:
    print("update_status definition not found!")

# 3. Fix update_status body - remove freemium logic
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

# Write back
with open('C:/Users/garvi/OneDrive/Documents/Projects/Hire-Edge-V2/backend/app.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("Done!")