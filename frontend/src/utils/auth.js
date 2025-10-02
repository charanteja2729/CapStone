// simple utils for token + headers
export function getToken() {
  try {
    return localStorage.getItem('token');
  } catch (e) {
    console.warn('getToken error', e);
    return null;
  }
}

// isJson -> include Content-Type: application/json
export function getAuthHeaders(isJson = false) {
  const headers = {};
  const token = getToken();
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }
  if (isJson) {
    headers['Content-Type'] = 'application/json';
  }
  return headers;
}

export function removeToken() {
  try {
    localStorage.removeItem('token');
  } catch (e) {
    console.warn('removeToken error', e);
  }
}
