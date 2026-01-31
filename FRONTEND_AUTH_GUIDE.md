# Frontend Authentication Implementation Guide (Supabase + FastAPI)

This guide details how to implement the new Authentication flow on the frontend.

## 1. Setup

### Install Dependencies
```bash
npm install @supabase/supabase-js
```

### Configuration (`src/lib/supabase.ts`)
Create a single instance of the Supabase client to be used throughout the app.

```typescript
import { createClient } from '@supabase/supabase-js'

const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL!
const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!

export const supabase = createClient(supabaseUrl, supabaseAnonKey)
```

---

## 2. Sign Up (Email/Password)

Use this when user fills out your custom Signup Form.

```typescript
const handleSignup = async (email, password, role, name, surname, specialization = null, doctor_register_number = null) => {
  const { data, error } = await supabase.auth.signUp({
    email,
    password,
    options: {
      // CRITICAL: This metadata triggers the Backend DB insert
      data: {
        role: role, // 'doctor' or 'patient'
        name: name,
        surname: surname,
        specialization: specialization,      // Optional
        doctor_register_number: doctor_register_number // Optional (for doctors)
      }
    }
  })

  if (error) {
    console.error("Signup failed:", error.message)
    alert(error.message)
    return
  }

  // Check if session is null (Means email confirmation is required)
  if (data.user && !data.session) {
    // Redirect to a "Check Email" page
    // router.push('/auth/check-email')
    alert("Account created! Please check your email to confirm.")
  }
}
```

---

## 3. Login (Email/Password)

Use this for your main Login screen. Handles routing logic.

```typescript
import { useRouter } from 'next/navigation'

const handleLogin = async (email, password) => {
  const router = useRouter()
  
  // 1. Authenticate
  const { data, error } = await supabase.auth.signInWithPassword({
    email,
    password
  })

  if (error) {
    alert(error.message)
    return
  }

  // 2. Routing Logic (Check Role)
  await checkRoleAndRedirect(data.user.id, router)
}

// Helper function for redirection
const checkRoleAndRedirect = async (userId, router) => {
  // Fetch profile from YOUR public.users table (Best Practice: Fetch fresh role)
  const { data: profile } = await supabase
    .from('users')
    .select('role')
    .eq('id', userId)
    .single()

  if (!profile) {
    // Should not happen if Trigger is working
    console.error("Profile missing!") 
    return
  }

  if (profile.role === 'unassigned') {
    router.push('/onboarding') // Google Login Strategy
  } else if (profile.role === 'doctor') {
    router.push('/doctor-dashboard')
  } else if (profile.role === 'patient') {
    router.push('/patient-dashboard')
  } else if (profile.role === 'admin') {
    router.push('/admin')
  }
}
```

---
# ... (Sections 4, 5, 6 remain unchanged) ...

## 7. Password Reset Flow

**Step 1: Request Reset (Forgot Password Page)**
```typescript
const handleResetRequest = async (email) => {
  const { error } = await supabase.auth.resetPasswordForEmail(email, {
    // URL to your local "Enter New Password" page
    redirectTo: 'http://localhost:3000/update-password', 
  })
  
  if (error) alert(error.message)
  else alert("Check your email for the reset link")
}
```

**Step 2: Update Password (Update Password Page)**
*When user clicks email link, they are logged in and redirected here.*
```typescript
const handlePasswordUpdate = async (newPassword) => {
  const { error } = await supabase.auth.updateUser({ 
    password: newPassword 
  })

  if (error) alert("Update failed")
  else {
    alert("Password updated! Redirecting...")
    router.push('/dashboard') // or call checkRoleAndRedirect
  }
}
```
