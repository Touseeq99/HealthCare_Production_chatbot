# Metamed Backend API

Comprehensive healthcare chatbot backend with role-based access control, secure authentication, and real-time chat functionality.

## Table of Contents
- [API Structure](#api-structure)
- [Authentication](#authentication)
  - [User Registration](#user-registration)
  - [User Login](#user-login)
  - [Token Management](#token-management)
- [User Roles](#user-roles)
  - [Patient](#patient)
  - [Doctor](#doctor)
  - [Admin](#admin)
- [Chat Features](#chat-features)
  - [Patient Chat](#patient-chat)
  - [Doctor Chat](#doctor-chat)
- [Article Management](#article-management)
- [User Management](#user-management)
- [Error Handling](#error-handling)
- [Security](#security)
- [Rate Limiting](#rate-limiting)
- [Deployment](#deployment)

## API Structure

### Base URL
`https://api.metamed.example.com/v1`

### Authentication
- All endpoints (except `/auth/*`) require authentication
- Include JWT token in the `Authorization` header: `Bearer <token>`

## Authentication

### User Registration

#### Register as Patient
```http
POST /auth/register
Content-Type: application/json

{
  "email": "patient@example.com",
  "password": "SecurePass123!",
  "name": "John",
  "surname": "Doe",
  "role": "patient",
  "phone": "+1234567890"
}
```

#### Register as Doctor
```http
POST /auth/register
Content-Type: application/json

{
  "email": "doctor@example.com",
  "password": "DoctorPass123!",
  "name": "Sarah",
  "surname": "Smith",
  "role": "doctor",
  "phone": "+1987654321",
  "specialization": "Cardiology",
  "doctor_register_number": "DR12345"
}
```

### User Login
```http
POST /auth/token
Content-Type: application/json

{
  "email": "user@example.com",
  "password": "UserPass123!",
  "role": "patient"
}
```

### Token Management
- **Access Token**: Valid for 1 hour
- **Refresh Token**: Valid for 7 days
- **Token Refresh**:
  ```http
  POST /auth/refresh
  Authorization: Bearer <refresh_token>
  ```

## User Roles

### Patient
- Chat with medical assistant
- View published articles
- View doctor profiles
- Manage personal health information

### Doctor
- All patient permissions
- Access to medical chat with advanced features
- Publish articles (pending admin approval)
- View patient history (with consent)

### Admin
- All doctor permissions
- User management
- Article approval/publishing
- System monitoring
- Content moderation

## Chat Features

### Patient Chat
```http
POST /chat/patient/stream
Authorization: Bearer <token>
Content-Type: application/json

{
  "message": "What are the symptoms of flu?",
  "conversation_id": "optional_conversation_id"
}
```

### Doctor Chat
```http
POST /chat/doctor/stream
Authorization: Bearer <token>
Content-Type: application/json

{
  "message": "Differential diagnosis for chest pain",
  "patient_context": {
    "age": 45,
    "gender": "male",
    "medical_history": ["hypertension", "high_cholesterol"]
  }
}
```

## Article Management

### Create Article (Admin)
```http
POST /admin/articles
Authorization: Bearer <admin_token>
Content-Type: application/json

{
  "title": "Understanding Diabetes",
  "content": "Detailed article content...",
  "summary": "Brief summary...",
  "category": "Chronic Conditions",
  "is_published": true,
  "tags": ["diabetes", "health", "chronic"]
}
```

### List Articles
```http
GET /articles?page=1&limit=10&category=Chronic+Conditions
```

## User Management (Admin)

### List Users
```http
GET /admin/users?role=doctor&status=active
Authorization: Bearer <admin_token>
```

### Update User Status
```http
PATCH /admin/users/{user_id}/status
Authorization: Bearer <admin_token>
Content-Type: application/json

{
  "status": "active" | "suspended" | "pending"
}
```

## Error Handling

### Common Error Responses

#### 400 Bad Request
```json
{
  "detail": "Invalid request data"
}
```

#### 401 Unauthorized
```json
{
  "detail": "Invalid authentication credentials"
}
```

#### 403 Forbidden
```json
{
  "detail": "Insufficient permissions"
}
```

#### 404 Not Found
```json
{
  "detail": "Resource not found"
}
```

## Security

### Password Requirements
- Minimum 12 characters
- At least 1 uppercase letter
- At least 1 lowercase letter
- At least 1 number
- At least 1 special character

### Rate Limiting
- Authentication endpoints: 5 requests per minute
- API endpoints: 100 requests per minute
- Chat endpoints: 30 requests per minute

## Deployment

### Environment Variables
```env
DATABASE_URL=postgresql://user:password@localhost:5432/metamed
SECRET_KEY=your-secret-key-here
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=60
REFRESH_TOKEN_EXPIRE_DAYS=7
ENVIRONMENT=production
```

### Docker
```bash
docker-compose up --build
```

### Health Check
```http
GET /health
```

## Support
For support, please contact support@metamed.example.com

## License
This project is licensed under the MIT License.
    "specialization": "Cardiology",
    "doctor_register_number": "DOC12345"
  }
}
```

### Verify Token
Verify if the provided token is valid.

**Endpoint**: `GET /api/auth/verify-token`

**Headers**:
```
Authorization: Bearer <token>
```

**Response**:
```json
{
  "success": true,
  "message": "Token is valid"
}
```

## Chat

### Doctor Chat
Stream chat responses for doctors.

**Endpoint**: `POST /api/chat/doctor/stream`

**Headers**:
```
Authorization: Bearer <token>
Content-Type: application/json
```

**Request Body**:
```json
{
  "message": "What are the symptoms of diabetes?"
}
```

**Response**:
```
data: {"message": "The symptoms of diabetes include..."}

```

### Patient Chat
Stream chat responses for patients.

**Endpoint**: `POST /api/chat/patient/stream`

**Headers**:
```
Authorization: Bearer <token>
Content-Type: application/json
```

**Request Body**:
```json
{
  "message": "I've been experiencing headaches and fatigue."
}
```

**Response**:
```
data: {"message": "I understand you're experiencing headaches and fatigue..."}

```

## Error Responses

### 400 Bad Request
```json
{
  "detail": "Invalid request data"
}
```

### 401 Unauthorized
```json
{
  "detail": "Could not validate credentials"
}
```

### 403 Forbidden
```json
{
  "detail": "Account locked. Please try again later."
}
```

### 404 Not Found
```json
{
  "detail": "User not found"
}
```

### 500 Internal Server Error
```json
{
  "detail": "Internal server error"
}
```

## Security

- All endpoints except `/api/auth/register` and `/api/auth/token` require authentication
- Passwords are hashed using bcrypt
- JWT tokens are used for authentication
- Rate limiting is implemented to prevent brute force attacks
- Account lockout after multiple failed login attempts

## Environment Variables

- `SECRET_KEY`: Secret key for JWT token generation
- `ALGORITHM`: Algorithm for JWT (default: HS256)
- `ACCESS_TOKEN_EXPIRE_MINUTES`: Token expiration time in minutes
- `MAX_LOGIN_ATTEMPTS`: Maximum number of login attempts before account lockout
- `LOCKOUT_TIME`: Time in seconds to lock the account after too many failed attempts