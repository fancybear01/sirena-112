import { Navigate, Route, Routes } from 'react-router';
import { pathForRole, type CurrentUser } from './api/auth';
import { AuthSessionProvider, useAuthSession } from './auth/AuthSession';
import { AdminPage } from './features/admin/AdminPage';
import { TrainingBoardPage } from './features/board/TrainingBoardPage';
import { StudentPage } from './features/student/StudentPage';
import { TeacherPage } from './features/teacher/TeacherPage';
import { AppLayout } from './layout/AppLayout';
import { LoginPage } from './pages/LoginPage';
import { NotFoundPage } from './pages/NotFoundPage';

function Protected({ role, children }: { role: CurrentUser['role']; children: React.ReactNode }) {
  const { status, user } = useAuthSession();
  if (status === 'loading') {
    return <div className="route-loading" role="status" aria-live="polite">Проверяем сессию…</div>;
  }
  if (status === 'anonymous') return <Navigate to="/login" replace />;
  if (user.role !== role) return <Navigate to={pathForRole(user.role)} replace />;
  return children;
}

export function App() {
  return (
    <AuthSessionProvider>
      <Routes>
        <Route path="/" element={<Navigate to="/login" replace />} />
        <Route path="/login" element={<LoginPage />} />
        <Route path="/board" element={<Protected role="TEACHER"><TrainingBoardPage /></Protected>} />
        <Route element={<AppLayout />}>
          <Route path="/admin" element={<Protected role="ADMIN"><AdminPage /></Protected>} />
          <Route path="/teacher" element={<Protected role="TEACHER"><TeacherPage /></Protected>} />
          <Route path="/student" element={<Protected role="STUDENT"><StudentPage /></Protected>} />
          <Route path="*" element={<NotFoundPage />} />
        </Route>
      </Routes>
    </AuthSessionProvider>
  );
}
