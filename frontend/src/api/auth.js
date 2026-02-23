import request from './request'

export const authApi = {
  login(data) {
    return request.post('/auth/login/', data)
  },
  
  register(data) {
    return request.post('/auth/register/', data)
  },
  
  logout(refreshToken) {
    return request.post('/auth/logout/', { refresh: refreshToken })
  },
  
  refresh(refreshToken) {
    return request.post('/auth/refresh/', { refresh: refreshToken })
  },
  
  me() {
    return request.get('/auth/me/')
  },
  
  updateProfile(data) {
    return request.patch('/auth/me/', data)
  },
  
  changePassword(data) {
    return request.post('/auth/change-password/', data)
  },
  
  renewVip(days) {
    return request.post('/auth/renew-vip/', { days })
  },
}
