with open('C:/Users/garvi/OneDrive/Documents/Projects/Hire-Edge-V2/backend/app.py', 'rb') as f:
    content = f.read()

# Find the truncation section - search for the bytes
# FREEMIUM TRUNCATION
pos1 = content.find(b'FREEMIUM TRUNCATION')
# Go back to find the start of the marker line (box drawing chars)
marker_start = content.rfind(b'\xe2\x95\x90\xe2\x95\x90\xe2\x95\x90\xe2\x95\x90', 0, pos1)
print('Marker start at:', marker_start)

# Find the third marker (BACKGROUND JOB RUNNER)
pos2 = content.find(b'BACKGROUND JOB RUNNER', pos1)
marker_end = content.find(b'\xe2\x95\x90\xe2\x95\x90\xe2\x95\x90\xe2\x95\x90', pos2)
print('Second marker end at:', marker_end)

# Find the start of the function after that
func_start = content.find(b'def run_job', marker_end)
print('run_job at:', func_start)

# Remove from marker_start to func_start
new_content = content[:marker_start] + content[func_start:]

print('Original length:', len(content))
print('New length:', len(new_content))
print('Removed:', len(content) - len(new_content), 'bytes')

# Write back
with open('C:/Users/garvi/OneDrive/Documents/Projects/Hire-Edge-V2/backend/app.py', 'wb') as f:
    f.write(new_content)

print('Done!')