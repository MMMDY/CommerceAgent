/** Maximum UI polling interval for release stop/rollback propagation. */
export const RELEASE_STATUS_REFRESH_MS = 15_000;

export const releaseStatusRefreshWithinSlo = () =>
  RELEASE_STATUS_REFRESH_MS <= 60_000;
