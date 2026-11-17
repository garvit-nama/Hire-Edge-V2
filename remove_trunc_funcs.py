with open('C:/Users/garvi/OneDrive/Documents/Projects/Hire-Edge-V2/backend/app.py', 'rb') as f:
    content = f.read()

# Remove truncation functions (bytes 57281 to 59152)
start = 57281
end = 59152

new_content = content[:start] + content[end:]

print(f'Original length: {len(content)}')
print(f'New length: {len(new_content)}')
print(f'Removed: {len(content) - len(new_content)} bytes')

with open('C:/Users/garvi/OneDrive/Documents/Projects/Hire-Edge-V2/backend/app.py', 'wb') as f:
    f.write(new_content)

print('Done!')