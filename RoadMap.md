# Healthcare Chatbot API Endpoints

## Authentication
- `POST /api/auth/login` - User login
  - Request: `{ email: string, password: string, role: string }`
  - Response: `{ token: string, refreshToken: string, expiresIn: number, user: any }`

- `POST /api/auth/refresh` - Refresh access token
  - Request: `{ refreshToken: string }`
  - Response: `{ token: string, expiresIn?: number, refreshToken?: string }`

- `POST /api/auth/signup` - User registration
  - Request: `{ name, surname, email, password, role, ... }`
  - Response: `{ success: boolean, data: any }`

## Admin Endpoints
- `GET /api/admin/users` - Get user statistics
  - Response: `{ totalUsers: number, activeUsers: number, activeDoctors: number, chatSessions: number }`

- `GET /api/admin/articles` - Get all blog posts
  - Response: `Array<{ id: string, title: string, content: string, ... }>`

- `GET /api/admin/documents` - Get uploaded documents
  - Response: `string[]` (list of document names/IDs)

## Chat Endpoints
- `POST /api/chat/doctor` - Process doctor chat messages
  - Request: `{ question: string, chatId: string, history: Message[] }`
  - Response: Chat response

## Article Endpoints
- `GET /api/articles` - Get public blog posts
  - Response: `Array<{ id: string, title: string, content: string, ... }>`

## Notes:
1. All authenticated endpoints (except login/refresh) require a valid JWT token in the `Authorization: Bearer <token>` header.
2. The API base URL is configured via `NEXT_PUBLIC_API_URL` environment variable.
3. The system uses token-based authentication with automatic refresh.
4. Error responses typically include a `message` field with error details.

## Database Schema (Inferred)
The following collections/tables are referenced:

### Users
- id: string
- email: string
- role: 'patient' | 'doctor' | 'admin'
- name: string
- surname: string
- phone?: string
- specialization?: string (for doctors)
- licenseNumber?: string (for doctors)
- doctorRegisterNumber?: string (for doctors)
- createdAt: Date
- updatedAt: Date

### Articles/Blog Posts
- id: string
- title: string
- content: string
- authorId: string (references Users.id)
- createdAt: Date
- updatedAt: Date

### Chat Sessions
- id: string
- userId: string (references Users.id)
- messages: Array<{ content: string, sender: string, timestamp: Date }>
- createdAt: Date
- updatedAt: Date