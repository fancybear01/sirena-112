import type { ApiConfig } from '../../../api/config';
import { createHttpClient, type HttpClient } from '../../../api/httpClient';
import type { TrainingBoardApi, TrainingBoardSnapshot } from './types';

export function createTrainingBoardHttpApi(
  config: Pick<ApiConfig, 'baseUrl'>,
  http: HttpClient = createHttpClient(config.baseUrl),
): TrainingBoardApi {
  return {
    getSnapshot: () => http.request<TrainingBoardSnapshot>('/api/teacher/board'),
  };
}
