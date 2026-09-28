import { createContext, useContext, useEffect, useMemo, useState } from 'react';
import { authApi, clearPrivateBrowserState, type CurrentUser } from '../api/auth';
import { authUnauthorizedEvent } from '../api/httpClient';

type AuthSession =
  | { status: 'loading'; user: null }
  | { status: 'anonymous'; user: null }
  | { status: 'authenticated'; user: CurrentUser };

type AuthSessionContextValue = AuthSession & {
  login(username: string, password: string): Promise<CurrentUser>;
  logout(): Promise<void>;
};

const AuthSessionContext = createContext<AuthSessionContextValue | null>(null);

export function AuthSessionProvider({ children }: { children: React.ReactNode }) {
  const [session, setSession] = useState<AuthSession>({ status: 'loading', user: null });

  useEffect(() => {
    let active = true;
    const expireSession = () => {
      clearPrivateBrowserState();
      setSession({ status: 'anonymous', user: null });
    };

    window.addEventListener(authUnauthorizedEvent, expireSession);
    void authApi.me()
      .then((user) => {
        if (active) setSession({ status: 'authenticated', user });
      })
      .catch(() => {
        if (active) expireSession();
      });

    return () => {
      active = false;
      window.removeEventListener(authUnauthorizedEvent, expireSession);
    };
  }, []);

  const value = useMemo<AuthSessionContextValue>(() => ({
    ...session,
    async login(username, password) {
      clearPrivateBrowserState();
      const user = await authApi.login(username, password);
      setSession({ status: 'authenticated', user });
      return user;
    },
    async logout() {
      try {
        await authApi.logout();
      } finally {
        clearPrivateBrowserState();
        setSession({ status: 'anonymous', user: null });
      }
    },
  }), [session]);

  return <AuthSessionContext.Provider value={value}>{children}</AuthSessionContext.Provider>;
}

export function useAuthSession(): AuthSessionContextValue {
  const value = useContext(AuthSessionContext);
  if (!value) throw new Error('useAuthSession must be used inside AuthSessionProvider');
  return value;
}
