import { useEffect, useState } from 'react';
import { Navigate, Route, Routes } from 'react-router';
import { authApi, pathForRole, secureAuth, type CurrentUser } from './api/auth';
import { AdminPage } from './features/admin/AdminPage';
import { StudentPage } from './features/student/StudentPage';
import { TeacherPage } from './features/teacher/TeacherPage';
import { AppLayout } from './layout/AppLayout';
import { LoginPage } from './pages/LoginPage';
import { NotFoundPage } from './pages/NotFoundPage';

function Protected({ role, children }: { role: CurrentUser['role']; children: React.ReactNode }) {
  const [user, setUser] = useState<CurrentUser | null | undefined>();
  useEffect(() => {
    if (!secureAuth) return;
    authApi.me().then(setUser).catch(() => setUser(null));
  }, []);
  if (!secureAuth) return children;
  if (user === undefined) return null;
  if (user === null) return <Navigate to="/login" replace />;
  if (user.role !== role) return <Navigate to={pathForRole(user.role)} replace />;
  return children;
}

export function App() {
  return (
    <Routes>
      <Route path="/" element={<Navigate to="/login" replace />} />
      <Route path="/login" element={<LoginPage />} />
      <Route element={<AppLayout />}>
        <Route path="/admin" element={<Protected role="ADMIN"><AdminPage /></Protected>} />
        <Route path="/teacher" element={<Protected role="TEACHER"><TeacherPage /></Protected>} />
        <Route path="/student" element={<Protected role="STUDENT"><StudentPage /></Protected>} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}
