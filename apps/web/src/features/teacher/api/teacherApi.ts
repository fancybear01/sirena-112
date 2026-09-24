import { apiConfig } from '../../../api/config';
import { createTeacherHttpApi } from './teacherHttpApi';
import { teacherMockApi } from './teacherMockApi';
import { createTeacherSessionEvents, pollingTeacherSessionEvents } from './teacherSessionEvents';

export const teacherApi = apiConfig.mode === 'api'
  ? createTeacherHttpApi(apiConfig)
  : teacherMockApi;

export const teacherSessionEvents = apiConfig.mode === 'api'
  ? createTeacherSessionEvents(apiConfig)
  : pollingTeacherSessionEvents;
