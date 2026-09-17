import { apiConfig } from '../../../api/config';
import { createStudentHttpApi } from './studentHttpApi';
import { studentMockApi } from './studentMockApi';

export const studentApi = apiConfig.mode === 'api'
  ? createStudentHttpApi(apiConfig)
  : studentMockApi;
