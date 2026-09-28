import { apiConfig } from '../../../api/config';
import { createTrainingBoardHttpApi } from './trainingBoardHttpApi';
import { trainingBoardMockApi } from './trainingBoardMockApi';

export const trainingBoardApi = apiConfig.mode === 'api'
  ? createTrainingBoardHttpApi(apiConfig)
  : trainingBoardMockApi;
