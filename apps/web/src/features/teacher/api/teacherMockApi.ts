import { scenarioFixtures } from './scenarios.fixture';
import type { TeacherApi, TeacherScenario, TeacherSession } from './types';

type MockOptions = {
  scenarios?: TeacherScenario[];
  delayMs?: number;
  failScenarios?: boolean;
};

function createEmptyCard(): TeacherSession['card'] {
  return {
    incidentType: null,
    signs: null,
    address: null,
    requiredServices: [],
    facts: {},
  };
}

function makeUuid() {
  return crypto.randomUUID();
}

export function createTeacherMockApi(options: MockOptions = {}): TeacherApi {
  const scenarios = options.scenarios ?? scenarioFixtures;
  const delayMs = options.delayMs ?? 250;
  const sessions = new Map<string, TeacherSession>();

  async function respond<T>(value: T): Promise<T> {
    if (delayMs > 0) {
      await new Promise((resolve) => window.setTimeout(resolve, delayMs));
    }
    return structuredClone(value);
  }

  return {
    async getScenarios() {
      if (options.failScenarios) {
        await respond(null);
        throw new Error('Mock scenarios request failed');
      }
      return respond(scenarios);
    },

    async launchSession(scenarioId) {
      const scenario = scenarios.find((item) => item.id === scenarioId);
      if (!scenario || scenario.status !== 'READY') {
        throw new Error('Scenario is not ready');
      }

      const startedAt = new Date().toISOString();
      const session: TeacherSession = {
        id: makeUuid(),
        scenarioId,
        mode: 'CARD',
        state: 'ACTIVE',
        card: createEmptyCard(),
        report: null,
        startedAt,
        endedAt: null,
      };
      sessions.set(session.id, session);
      return respond(session);
    },

    async stopSession(sessionId) {
      const session = sessions.get(sessionId);
      if (!session || session.state !== 'ACTIVE') {
        throw new Error('Active session not found');
      }

      const completed: TeacherSession = {
        ...session,
        state: 'COMPLETED',
        endedAt: new Date().toISOString(),
      };
      sessions.set(sessionId, completed);
      return respond(completed);
    },
  };
}

export const teacherMockApi = createTeacherMockApi();
