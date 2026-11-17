with open('C:/Users/garvi/OneDrive/Documents/Projects/Hire-Edge-V2/backend/app.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Find the update_status function and replace its body
import re

# Find the function definition
func_start = content.find("def update_status(status_str, progress_val, msg_str, results_dict=None, report_str=None):")
if func_start == -1:
    print("Function not found!")
else:
    print(f"Function at {func_start}")
    
    # Find the end of the function (next def or class at same indent)
    # The function body starts after the colon
    body_start = content.find(":", func_start) + 1
    
    # Find the next function definition at same indent level (4 spaces)
    # Look for "\n    def " or "\n\n    def "
    next_func = content.find("\n    def ", body_start)
    if next_func == -1:
        next_func = content.find("\n\n    def ", body_start)
    if next_func == -1:
        next_func = len(content)
    
    print(f"Body from {body_start} to {next_func}")
    
    # Replace the entire function body
    new_body = """
        job["status"] = status_str
        job["progress"] = progress_val
        job["message"] = msg_str
        if results_dict is not None: job["results"] = results_dict
        if report_str is not None: job["report"] = report_str
        job["agents"] = get_agents_status(progress_val, status_str, msg_str)
        
        try:
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
            }, room=job_id)
        except Exception as e:
            logging.warning(f"[socketio] emit failed for {job_id}: {e}"""
    
    new_content = content[:body_start] + new_body + content[next_func:]
    
    with open('C:/Users/garvi/OneDrive/Documents/Projects/Hire-Edge-V2/backend/app.py', 'w', encoding='utf-8') as f:
        f.write(new_content)
    
    print("Function body replaced!")