# Frontend Integration Guide

## 🚀 Quick Start

Your backend is **READY** for frontend connection!

---

## Backend Setup (Already Done ✅)

- ✅ CORS configured for common frontend ports
- ✅ JWT authentication system
- ✅ Swagger docs at `/api/docs`
- ✅ All Phase 3 & 4 endpoints implemented
- ✅ Rate limiting on question generation
- ✅ Background tasks for exam analysis

---

## Frontend Setup Steps

### 1. **Environment Variables**

Create `.env` in your frontend project:

```env
# React / Vite / Next.js
REACT_APP_API_URL=http://localhost:8000
VITE_API_URL=http://localhost:8000
NEXT_PUBLIC_API_URL=http://localhost:8000
```

### 2. **Install HTTP Client**

```bash
npm install axios
# or
yarn add axios
```

### 3. **Create API Client** (`src/api/client.js`)

```javascript
import axios from 'axios';

const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL || 'http://localhost:8000',
  withCredentials: true,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Request interceptor - Add JWT token
api.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('access_token');
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  },
  (error) => Promise.reject(error)
);

// Response interceptor - Handle token refresh
api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config;

    // If 401 and not already retried
    if (error.response?.status === 401 && !originalRequest._retry) {
      originalRequest._retry = true;

      try {
        const refreshToken = localStorage.getItem('refresh_token');
        const { data } = await axios.post(
          'http://localhost:8000/api/auth/refresh',
          { refresh_token: refreshToken }
        );

        localStorage.setItem('access_token', data.access_token);
        originalRequest.headers.Authorization = `Bearer ${data.access_token}`;
        
        return api(originalRequest);
      } catch (refreshError) {
        // Refresh failed - logout user
        localStorage.removeItem('access_token');
        localStorage.removeItem('refresh_token');
        window.location.href = '/login';
        return Promise.reject(refreshError);
      }
    }

    return Promise.reject(error);
  }
);

export default api;
```

### 4. **Create Auth Service** (`src/api/auth.js`)

```javascript
import api from './client';

export const authService = {
  /**
   * Register new user
   */
  async register(email, password, languageId, experienceLevel) {
    const { data } = await api.post('/api/auth/register', {
      email,
      password,
      language_id: languageId,
      experience_level: experienceLevel
    });
    
    // Store tokens
    localStorage.setItem('access_token', data.access_token);
    localStorage.setItem('refresh_token', data.refresh_token);
    
    return data;
  },

  /**
   * Login user
   */
  async login(email, password) {
    const { data } = await api.post('/api/auth/login', {
      email,
      password
    });
    
    // Store tokens
    localStorage.setItem('access_token', data.access_token);
    localStorage.setItem('refresh_token', data.refresh_token);
    
    return data.user;
  },

  /**
   * Logout user
   */
  async logout() {
    try {
      await api.post('/api/auth/logout');
    } catch (error) {
      // Even if logout fails, clear local tokens
      console.error('Logout API failed:', error);
    }
    
    localStorage.removeItem('access_token');
    localStorage.removeItem('refresh_token');
    window.location.href = '/login';
  },

  /**
   * Get current user profile
   */
  async getProfile() {
    const { data } = await api.get('/api/auth/me');
    return data;
  },

  /**
   * Change password
   */
  async changePassword(currentPassword, newPassword) {
    const { data } = await api.post('/api/auth/change-password', {
      current_password: currentPassword,
      new_password: newPassword
    });
    return data;
  },

  /**
   * Check if user is authenticated
   */
  isAuthenticated() {
    return !!localStorage.getItem('access_token');
  }
};
```

### 5. **Create Exam Service** (`src/api/exam.js`)

```javascript
import api from './client';

export const examService = {
  /**
   * Start new exam
   */
  async startExam(languageId, mappingId, difficulty = 0.5) {
    const { data } = await api.post('/api/exam/start', {
      language_id: languageId,
      mapping_id: mappingId,
      difficulty
    });
    return data;
  },

  /**
   * Submit exam answers
   */
  async submitExam(sessionId, responses) {
    const { data } = await api.post('/api/exam/submit', {
      session_id: sessionId,
      responses
    });
    return data;
  },

  /**
   * Get exam analysis
   */
  async getAnalysis(sessionId) {
    const { data } = await api.get(`/api/exam/analysis/${sessionId}`);
    return data;
  }
};
```

### 6. **Create Question Service** (`src/api/questions.js`)

```javascript
import api from './client';

export const questionService = {
  /**
   * Generate new questions (rate limited: 50/min)
   */
  async generateQuestions(languageId, mappingId, count = 50, difficulty = 0.5) {
    const { data } = await api.post('/api/question-bank/generate', {
      language_id: languageId,
      mapping_id: mappingId,
      count,
      difficulty
    });
    return data;
  },

  /**
   * Select questions for exam
   */
  async selectQuestions(languageId, mappingId, difficulty, count = 10) {
    const { data } = await api.post('/api/question-bank/select', {
      language_id: languageId,
      mapping_id: mappingId,
      difficulty,
      count
    });
    return data;
  },

  /**
   * Mark questions as seen/viewed
   */
  async markQuestionsSeen(questionIds) {
    const { data } = await api.post('/api/question-bank/mark-seen', {
      question_ids: questionIds
    });
    return data;
  },

  /**
   * Check question warehouse status
   */
  async getWarehouseStatus(languageId, mappingId, difficulty) {
    const { data } = await api.get('/api/question-bank/warehouse-status', {
      params: {
        language_id: languageId,
        mapping_id: mappingId,
        difficulty
      }
    });
    return data;
  },

  /**
   * Report a question
   */
  async reportQuestion(questionId, reason, description) {
    const { data } = await api.post('/api/question-bank/report', {
      question_id: questionId,
      report_reason: reason,
      description
    });
    return data;
  },

  /**
   * Get question analytics
   */
  async getQuestionAnalytics(questionId) {
    const { data } = await api.get(`/api/question-bank/analytics/${questionId}`);
    return data;
  },

  /**
   * Get analytics summary (admin only)
   */
  async getAnalyticsSummary(filters = {}) {
    const { data } = await api.get('/api/question-bank/analytics/summary', {
      params: filters
    });
    return data;
  },

  /**
   * Admin: Review question
   */
  async reviewQuestion(questionId, action, feedback = null, qualityScore = null) {
    const { data } = await api.post('/api/question-bank/admin/review', {
      question_id: questionId,
      action, // 'approve' or 'reject'
      feedback,
      quality_score: qualityScore
    });
    return data;
  },

  /**
   * Admin: Get pending questions
   */
  async getPendingQuestions(filters = {}) {
    const { data } = await api.get('/api/question-bank/admin/pending', {
      params: filters
    });
    return data;
  }
};
```

### 7. **Create RL Service** (`src/api/rl.js`)

```javascript
import api from './client';

export const rlService = {
  /**
   * Get RL recommendation for next topic
   */
  async getRecommendation(userId, languageId, strategy = 'ppo') {
    const { data } = await api.post('/api/rl/recommend', {
      user_id: userId,
      language_id: languageId,
      strategy
    });
    return data;
  },

  /**
   * Get RL system health/status
   */
  async getHealth() {
    const { data } = await api.get('/api/rl/health');
    return data;
  },

  /**
   * Get available RL strategies
   */
  async getStrategies() {
    const { data } = await api.get('/api/rl/strategies');
    return data;
  },

  /**
   * Get user's RL decision history
   */
  async getHistory(userId) {
    const { data } = await api.get(`/api/rl/history/${userId}`);
    return data;
  }
};
```

### 8. **Create Analytics Service** (`src/api/analytics.js`)

```javascript
import api from './client';

export const analyticsService = {
  /**
   * Get student analytics profile
   */
  async getStudentProfile(userId) {
    const { data } = await api.get(`/api/analytics/student/${userId}/profile`);
    return data;
  },

  /**
   * Get cross-topic analysis for student
   */
  async getCrossTopicAnalysis(userId) {
    const { data } = await api.get(`/api/analytics/student/${userId}/cross-topic-analysis`);
    return data;
  },

  /**
   * Get personalized recommendations
   */
  async getRecommendations(userId) {
    const { data } = await api.get(`/api/analytics/student/${userId}/recommendations`);
    return data;
  },

  /**
   * Get error patterns for specific subtopic
   */
  async getSubtopicErrors(subTopic) {
    const { data } = await api.get(`/api/analytics/subtopic/${subTopic}/errors`);
    return data;
  },

  /**
   * Get class-wide insights (admin only)
   */
  async getClassInsights(filters = {}) {
    const { data } = await api.get('/api/analytics/class-insights', {
      params: filters
    });
    return data;
  },

  /**
   * Get multi-level analytics
   */
  async getMultiLevel(userId, languageId) {
    const { data } = await api.get('/api/analytics/multi-level', {
      params: {
        user_id: userId,
        language_id: languageId
      }
    });
    return data;
  },

  /**
   * Get error pattern analysis
   */
  async getErrorPatterns(userId, languageId, mappingId = null) {
    const { data } = await api.get('/api/analytics/error-patterns', {
      params: {
        user_id: userId,
        language_id: languageId,
        mapping_id: mappingId
      }
    });
    return data;
  }
};
```

---

## Example: Login Flow (React)

```jsx
import { useState } from 'react';
import { authService } from './api/auth';

function LoginPage() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');

  const handleLogin = async (e) => {
    e.preventDefault();
    setError('');

    try {
      const user = await authService.login(email, password);
      console.log('Logged in:', user);
      // Redirect to dashboard
      window.location.href = '/dashboard';
    } catch (err) {
      if (err.response?.status === 401) {
        setError('Invalid email or password');
      } else if (err.response?.status === 429) {
        setError('Too many login attempts. Please try again later.');
      } else {
        setError('Login failed. Please try again.');
      }
    }
  };

  return (
    <form onSubmit={handleLogin}>
      <input
        type="email"
        placeholder="Email"
        value={email}
        onChange={(e) => setEmail(e.target.value)}
        required
      />
      <input
        type="password"
        placeholder="Password"
        value={password}
        onChange={(e) => setPassword(e.target.value)}
        required
      />
      {error && <p className="error">{error}</p>}
      <button type="submit">Login</button>
    </form>
  );
}
```

---

## Example: Exam Flow (React)

```jsx
import { useState, useEffect } from 'react';
import { examService } from './api/exam';

function ExamPage() {
  const [exam, setExam] = useState(null);
  const [answers, setAnswers] = useState({});
  const [analysis, setAnalysis] = useState(null);

  // Start exam
  const startExam = async () => {
    const examData = await examService.startExam('python_3', 'variables', 0.5);
    setExam(examData);
  };

  // Submit exam
  const submitExam = async () => {
    const result = await examService.submitExam(exam.session_id, answers);
    
    // Wait a bit for background analysis to complete
    setTimeout(async () => {
      const analysisData = await examService.getAnalysis(exam.session_id);
      setAnalysis(analysisData);
    }, 2000);
  };

  return (
    <div>
      {!exam && <button onClick={startExam}>Start Exam</button>}
      
      {exam && !analysis && (
        <div>
          <h2>Exam Questions</h2>
          {exam.questions.map((q, idx) => (
            <div key={idx}>
              <p>{q.question}</p>
              {/* Render options and collect answers */}
            </div>
          ))}
          <button onClick={submitExam}>Submit</button>
        </div>
      )}
      
      {analysis && (
        <div>
          <h2>Exam Results</h2>
          <p>Score: {analysis.score}/100</p>
          <h3>Personalized Feedback:</h3>
          <ul>
            {analysis.bullets.map((bullet, idx) => (
              <li key={idx}>{bullet}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
```

---

## API Response Formats

### Success Response
```json
{
  "user_id": "abc123",
  "score": 85,
  "mastery_score": 0.75
}
```

### Error Response (Validation)
```json
{
  "detail": [
    {
      "loc": ["body", "email"],
      "msg": "field required",
      "type": "value_error.missing"
    }
  ]
}
```

### Error Response (Generic)
```json
{
  "detail": "Invalid credentials"
}
```

---

## Testing Your Integration

### 1. **Test with Swagger UI**
Visit: http://localhost:8000/api/docs
- Try registering a user
- Try logging in
- Copy the JWT token
- Click "Authorize" button and paste token
- Test protected endpoints

### 2. **Test CORS**
```bash
python test_cors.py
```

### 3. **Test with Postman**
1. Import endpoints from Swagger
2. Set Authorization: Bearer <token>
3. Test each endpoint

---

## Common Issues & Solutions

### Issue: "CORS policy: No 'Access-Control-Allow-Origin' header"
**Solution:** Backend already configured! Make sure:
- Backend is running on port 8000
- Frontend is on port 3000/5173/4200
- Using `withCredentials: true` in axios config

### Issue: "401 Unauthorized" on every request
**Solution:** 
- Check if token is in localStorage
- Verify Authorization header format: `Bearer <token>`
- Token might be expired (15 min expiry)

### Issue: "429 Too Many Requests" on question generation
**Solution:**
- Rate limit is 50 requests/minute
- Wait 60 seconds or reduce request frequency

### Issue: Exam analysis returns empty bullets
**Solution:**
- Background task takes ~2-5 seconds
- Poll the analysis endpoint or wait before fetching
- Check `analysis_status` field (should be "completed")

---

## Production Deployment Notes

### Backend
1. Update CORS origins in `main.py`:
   ```python
   allow_origins=[
       "https://yourfrontend.com",
       "https://www.yourfrontend.com"
   ]
   ```

2. Set environment variables:
   ```bash
   SECRET_KEY=<your-production-secret>
   OPENAI_API_KEY=<your-key>
   DATABASE_URL=postgresql://...
   ```

3. Use production WSGI server:
   ```bash
   gunicorn main:app -w 4 -k uvicorn.workers.UvicornWorker
   ```

### Frontend
1. Update API URL to production backend
2. Enable HTTPS
3. Set secure cookie flags if using cookies

---

## Need Help?

📚 **API Documentation:** http://localhost:8000/api/docs  
📖 **ReDoc:** http://localhost:8000/api/redoc  
🔍 **Available Endpoints:** See `API_READINESS_CHECKLIST.md`

---

**Status:** ✅ **READY FOR FRONTEND INTEGRATION**

All systems operational! 🚀
