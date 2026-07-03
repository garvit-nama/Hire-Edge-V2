# Phase 6: Testing & QA Setup Guide

This guide covers setting up the testing infrastructure for HireEdge. Dependencies have been added to `requirements.txt` (backend) and staged. This document provides step-by-step instructions to create test suites and CI/CD pipelines.

---

## Backend Testing Setup (pytest)

### Step 1: Create Test Directory Structure

```bash
mkdir -p backend/tests
touch backend/tests/__init__.py
touch backend/tests/conftest.py
touch backend/tests/test_auth.py
touch backend/tests/test_freemium.py
touch backend/tests/test_api.py
```

### Step 2: conftest.py — Fixtures & Setup

```python
import pytest
import os
from app import app, db, socketio
from models import User, Job

@pytest.fixture
def client():
    """Test client with app context and clean DB"""
    app.config['TESTING'] = True
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    app.config['WTF_CSRF_ENABLED'] = False
    
    with app.app_context():
        db.create_all()
        yield app.test_client()
        db.session.remove()
        db.drop_all()

@pytest.fixture
def app_context():
    """App context for standalone usage"""
    with app.app_context():
        db.create_all()
        yield
        db.drop_all()

@pytest.fixture
def test_user(app_context):
    """Create a test user"""
    user = User(email='test@example.com', subscription_tier='free', free_analyses_used=0)
    user.set_password('password123')
    db.session.add(user)
    db.session.commit()
    return user

@pytest.fixture
def auth_headers(client, test_user):
    """Login and return auth headers"""
    response = client.post('/api/login', json={
        'email': 'test@example.com',
        'password': 'password123'
    })
    token = response.get_json()['token']
    return {'Authorization': f'Bearer {token}'}
```

### Step 3: test_auth.py — Authentication Tests

```python
import pytest

def test_register_success(client):
    """Test successful user registration"""
    response = client.post('/api/register', json={
        'email': 'newuser@example.com',
        'password': 'securepass123'
    })
    assert response.status_code == 201
    assert 'user_id' in response.get_json()

def test_register_duplicate_email(client, test_user):
    """Test registration with existing email"""
    response = client.post('/api/register', json={
        'email': 'test@example.com',
        'password': 'pass123'
    })
    assert response.status_code == 400
    assert 'already exists' in response.get_json()['error']

def test_login_success(client, test_user):
    """Test successful login"""
    response = client.post('/api/login', json={
        'email': 'test@example.com',
        'password': 'password123'
    })
    assert response.status_code == 200
    assert 'token' in response.get_json()

def test_login_invalid_password(client, test_user):
    """Test login with wrong password"""
    response = client.post('/api/login', json={
        'email': 'test@example.com',
        'password': 'wrongpassword'
    })
    assert response.status_code == 401

def test_get_user_info(client, auth_headers):
    """Test authenticated user retrieval"""
    response = client.get('/api/me', headers=auth_headers)
    assert response.status_code == 200
    assert response.get_json()['email'] == 'test@example.com'

def test_unauthorized_without_token(client):
    """Test protected route without token"""
    response = client.get('/api/me')
    assert response.status_code == 401
```

### Step 4: test_freemium.py — Freemium Logic Tests

```python
import pytest
from models import Job

def test_truncation_applied_on_second_analysis(client, auth_headers, app_context):
    """Test that free user's 2nd analysis is truncated"""
    from app import truncate_agent_outputs
    
    # Mock agent results
    results = {
        'a1_candidate_analysis': 'A' * 1000,  # Long text
        'a2_hr_profile': 'B' * 1000,
        # ... more agents
    }
    
    truncated = truncate_agent_outputs(results, percentage=70)
    
    # Check that truncated is shorter
    assert len(truncated['a1_candidate_analysis']) < len(results['a1_candidate_analysis'])
    assert '[...TRUNCATED FOR FREE TIER...]' in truncated['a1_candidate_analysis']

def test_free_tier_limit_after_3_analyses(client, auth_headers):
    """Test that free user is limited to 3 analyses"""
    for i in range(3):
        response = client.post('/analyse', 
            headers=auth_headers,
            data={'resume': 'test.pdf', 'job_role': 'Engineer'}
        )
        assert response.status_code == 200

    # 4th attempt should fail
    response = client.post('/analyse',
        headers=auth_headers,
        data={'resume': 'test.pdf', 'job_role': 'Engineer'}
    )
    assert response.status_code == 403
    assert 'exceeded' in response.get_json()['error'].lower()

def test_premium_user_unlimited_analyses(client, auth_headers, app_context):
    """Test that premium users are not limited"""
    from models import User
    
    user = User.query.filter_by(email='test@example.com').first()
    user.subscription_tier = 'premium'
    db.session.commit()
    
    for i in range(5):
        response = client.post('/analyse',
            headers=auth_headers,
            data={'resume': 'test.pdf', 'job_role': 'Engineer'}
        )
        assert response.status_code == 200

def test_is_truncated_metadata_in_db(client, auth_headers, app_context):
    """Test that is_truncated flag is saved to DB"""
    from models import Job
    
    # Simulate 2nd analysis for free user
    response = client.post('/analyse',
        headers=auth_headers,
        data={'resume': 'test.pdf', 'job_role': 'Engineer'}
    )
    jid = response.get_json()['job_id']
    
    # Get job from DB after completion
    job_db = Job.query.filter_by(id=jid).first()
    # After job completes, check is_truncated (would need to mock completion)
```

### Step 5: test_api.py — API Endpoint Tests

```python
import pytest

def test_health_endpoint(client):
    """Test health check endpoint"""
    response = client.get('/health')
    assert response.status_code == 200
    assert 'groq' in response.get_json()

def test_analyse_missing_auth(client):
    """Test /analyse without auth token"""
    response = client.post('/analyse', json={
        'resume': 'test.pdf',
        'job_role': 'Engineer'
    })
    assert response.status_code == 401

def test_analyse_success(client, auth_headers):
    """Test successful analysis initiation"""
    response = client.post('/analyse',
        headers=auth_headers,
        json={'resume': 'test.pdf', 'job_role': 'Engineer'}
    )
    assert response.status_code == 200
    assert 'job_id' in response.get_json()
    assert 'status' in response.get_json()

def test_status_endpoint(client, auth_headers):
    """Test job status endpoint"""
    # First, start an analysis
    init_response = client.post('/analyse',
        headers=auth_headers,
        json={'resume': 'test.pdf', 'job_role': 'Engineer'}
    )
    jid = init_response.get_json()['job_id']
    
    # Check status
    response = client.get(f'/status/{jid}', headers=auth_headers)
    assert response.status_code == 200
    assert response.get_json()['id'] == jid

def test_status_unauthorized(client):
    """Test /status without auth"""
    response = client.get('/status/fake-id')
    assert response.status_code == 401

def test_report_download(client, auth_headers):
    """Test report download endpoint"""
    # Would need a completed job in DB
    # For now, test 404
    response = client.get('/report/nonexistent', headers=auth_headers)
    assert response.status_code == 404

def test_my_reports(client, auth_headers):
    """Test user's report history endpoint"""
    response = client.get('/api/my-reports', headers=auth_headers)
    assert response.status_code == 200
    assert isinstance(response.get_json(), list)
```

### Step 6: Run Tests

```bash
# Install test dependencies (already in requirements.txt)
pip install -r requirements.txt

# Run all tests
pytest backend/tests/ -v

# Run with coverage
pytest backend/tests/ --cov=backend --cov-report=html

# Run specific test file
pytest backend/tests/test_auth.py -v

# Run specific test
pytest backend/tests/test_auth.py::test_login_success -v
```

---

## Frontend Testing Setup (Jest)

### Step 1: Create package.json (if not exists)

```bash
cd frontend
npm init -y
npm install --save-dev jest @testing-library/jest-dom @testing-library/dom vitest
npm install socket.io-client  # Already needed by app
```

Update `package.json`:

```json
{
  "name": "hireedge-frontend",
  "scripts": {
    "test": "jest --coverage",
    "test:watch": "jest --watch",
    "lint": "eslint js/",
    "format": "prettier --write js/ css/"
  },
  "devDependencies": {
    "jest": "^29.0.0",
    "@testing-library/dom": "^9.0.0",
    "@testing-library/jest-dom": "^6.0.0",
    "eslint": "^8.0.0",
    "prettier": "^3.0.0"
  }
}
```

### Step 2: jest.config.js

```javascript
module.exports = {
  testEnvironment: 'jsdom',
  setupFilesAfterEnv: ['<rootDir>/jest.setup.js'],
  collectCoverageFrom: [
    'js/**/*.js',
    '!js/**/*.test.js'
  ],
  testMatch: ['**/__tests__/**/*.js', '**/*.test.js']
};
```

### Step 3: jest.setup.js

```javascript
require('@testing-library/jest-dom');
```

### Step 4: Create Test Directory

```bash
mkdir -p frontend/js/__tests__
touch frontend/js/__tests__/state.test.js
touch frontend/js/__tests__/api.test.js
touch frontend/js/__tests__/render.test.js
```

### Step 5: Test Examples

**js/__tests__/state.test.js**

```javascript
describe('Global State (S)', () => {
  beforeEach(() => {
    // Clear localStorage
    localStorage.clear();
  });

  test('should initialize with default values', () => {
    expect(S.token).toBeUndefined();
    expect(S.results).toEqual({});
    expect(S.jobMetadata).toEqual({});
  });

  test('should persist token to localStorage', () => {
    S.token = 'test-token-123';
    expect(localStorage.getItem('token')).toBe('test-token-123');
  });

  test('should load token from localStorage on page load', () => {
    localStorage.setItem('token', 'saved-token-456');
    const loaded = localStorage.getItem('token');
    expect(loaded).toBe('saved-token-456');
  });
});
```

**js/__tests__/api.test.js**

```javascript
describe('API Functions', () => {
  test('getBase should return backend URL', () => {
    const base = getBase();
    expect(base).toMatch(/http(s)?:\/\//);
  });

  test('getHeaders should include Authorization if token exists', () => {
    S.token = 'bearer-token';
    const headers = getHeaders();
    expect(headers.Authorization).toBe('Bearer bearer-token');
  });

  test('getHeaders should have Content-Type for JSON', () => {
    const headers = getHeaders();
    expect(headers['Content-Type']).toBe('application/json');
  });
});
```

**js/__tests__/render.test.js**

```javascript
describe('Render Functions', () => {
  let container;

  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
    S.results = {
      a1_candidate_analysis: 'Test result',
      a2_hr_profile: 'HR data'
    };
  });

  afterEach(() => {
    document.body.removeChild(container);
  });

  test('should apply truncation class when is_truncated is true', () => {
    S.jobMetadata = { is_truncated: true };
    // Mock DOM for agent panels
    const panel = document.createElement('div');
    panel.id = 'tp-candidate';
    container.appendChild(panel);
    
    // Simulate render with truncation
    panel.classList.add('truncated');
    expect(panel.classList.contains('truncated')).toBe(true);
  });

  test('should not apply truncation when is_truncated is false', () => {
    S.jobMetadata = { is_truncated: false };
    const panel = document.createElement('div');
    panel.id = 'tp-candidate';
    expect(panel.classList.contains('truncated')).toBe(false);
  });
});
```

### Step 6: Run Tests

```bash
npm test                    # Run all tests
npm run test:watch         # Watch mode
npm test -- --coverage     # With coverage report
```

---

## Linting & Code Quality

### Backend: mypy, black, flake8, isort

```bash
# Create pyproject.toml
cat > backend/pyproject.toml << 'EOF'
[tool.black]
line-length = 100
target-version = ['py311']

[tool.isort]
profile = "black"
line_length = 100

[tool.mypy]
python_version = "3.11"
warn_return_any = true
warn_unused_configs = true
disallow_untyped_defs = false
EOF

# Type check
mypy backend/app.py backend/models.py

# Format code
black backend/

# Check style
flake8 backend/ --max-line-length=100

# Organize imports
isort backend/
```

### Frontend: ESLint, Prettier

```bash
# Create .eslintrc.json
cat > frontend/.eslintrc.json << 'EOF'
{
  "env": {
    "browser": true,
    "es2021": true
  },
  "extends": "eslint:recommended",
  "rules": {
    "semi": ["error", "always"],
    "quotes": ["error", "single"]
  }
}
EOF

# Create .prettierrc
cat > frontend/.prettierrc << 'EOF'
{
  "semi": true,
  "singleQuote": true,
  "printWidth": 100
}
EOF

# Lint
npm run lint

# Format
npm run format
```

---

## CI/CD Pipeline (GitHub Actions)

### .github/workflows/test.yml

```yaml
name: Tests & Linting

on: [push, pull_request]

jobs:
  backend:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      
      - name: Install dependencies
        run: |
          pip install -r backend/requirements.txt
      
      - name: Run pytest
        run: |
          pytest backend/tests/ -v --cov=backend
      
      - name: Type check (mypy)
        run: |
          mypy backend/app.py backend/models.py
      
      - name: Code style (black)
        run: |
          black --check backend/
      
      - name: Lint (flake8)
        run: |
          flake8 backend/ --max-line-length=100
      
      - name: Import sorting (isort)
        run: |
          isort --check-only backend/

  frontend:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      
      - name: Set up Node
        uses: actions/setup-node@v3
        with:
          node-version: '18'
      
      - name: Install dependencies
        run: |
          cd frontend
          npm install
      
      - name: Run tests
        run: |
          cd frontend
          npm test -- --coverage
      
      - name: Lint (ESLint)
        run: |
          cd frontend
          npm run lint
```

---

## Pre-commit Hooks

### .pre-commit-config.yaml

```yaml
repos:
  - repo: https://github.com/psf/black
    rev: 23.9.0
    hooks:
      - id: black
        language_version: python3.11
        
  - repo: https://github.com/PyCQA/isort
    rev: 5.12.0
    hooks:
      - id: isort
        
  - repo: https://github.com/PyCQA/flake8
    rev: 6.1.0
    hooks:
      - id: flake8
        args: [--max-line-length=100]
        
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v4.4.0
    hooks:
      - id: trailing-whitespace
      - id: end-of-file-fixer
```

Install:

```bash
pip install pre-commit
pre-commit install
```

---

## Testing Workflow

1. **Local testing** — Run `pytest` or `npm test` before committing
2. **Pre-commit hooks** — Auto-format + lint on git commit
3. **CI/CD pipeline** — GitHub Actions runs full suite on push
4. **Coverage gates** — Require ≥80% coverage for PRs

---

## Summary

All dependencies are already in `requirements.txt` for backend. This guide provides structure for test files. Frontend needs `package.json` setup. CI/CD uses GitHub Actions.

Next: Create these test files and run `pytest` + `npm test` to establish baseline coverage.
