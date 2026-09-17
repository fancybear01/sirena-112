import { apiConfig } from '../../../api/config';
import { createTeacherHttpApi } from './teacherHttpApi';
import { teacherMockApi } from './teacherMockApi';

export const teacherApi = apiConfig.mode === 'api'
  ? createTeacherHttpApi(apiConfig)
  : teacherMockApi;
