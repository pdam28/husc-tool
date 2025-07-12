import requests
from bs4 import BeautifulSoup
import base64
from flask import Flask, render_template, request, jsonify, session
import os
import time

# --- Class để làm việc với API anticaptcha.top ---
class AnticaptchaTopApi:
    def __init__(self, api_key):
        if not api_key:
            raise ValueError("API Key không được để trống.")
        self.api_key = api_key
        self.api_url = "https://anticaptcha.top/api/captcha"

    def solve(self, img_base64, captcha_type=1):
        payload = {'apikey': self.api_key, 'type': captcha_type, 'img': img_base64}
        try:
            response = requests.post(self.api_url, data=payload, timeout=60)
            response.raise_for_status()
            result_json = response.json()
            if result_json.get('success'):
                return {'status': True, 'captcha': result_json.get('captcha'), 'log': result_json.get('message')}
            else:
                return {'status': False, 'captcha': None, 'log': result_json.get('message', 'Lỗi không xác định từ API giải mã')}
        except Exception as e:
            return {'status': False, 'captcha': None, 'log': f"Lỗi mạng hoặc server giải mã: {e}"}

# --- Cấu hình Flask ---
app = Flask(__name__)
app.secret_key = 'a-secret-key-for-backend-loop' 

# --- Hàm đăng nhập ---
def do_login(req_session, base_url, username, password):
    try:
        login_post_url = base_url + "Account/Login"
        response = req_session.get(base_url)
        soup = BeautifulSoup(response.text, 'html.parser')
        token = soup.find('input', {'name': '__RequestVerificationToken'})['value']
        
        payload = { '__RequestVerificationToken': token, 'loginID': username, 'password': password }
        headers = {'Referer': base_url}
        req_session.post(login_post_url, data=payload, headers=headers)
        
        check_response = req_session.get(base_url)
        if check_response.status_code == 200:
            soup_checker = BeautifulSoup(check_response.text, 'html.parser')
            name_element = soup_checker.select_one("div.hitec-information > h5")
            if name_element:
                return True, name_element.get_text(strip=True)
    except Exception as e:
        return False, f"Lỗi trong quá trình đăng nhập: {e}"
    return False, "Tài khoản hoặc mật khẩu không đúng."

# --- API Endpoints ---
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/login", methods=['POST'])
def handle_login():
    data = request.json
    api_key = data.get('apiKey')
    if not api_key:
        return jsonify({"success": False, "message": "Vui lòng nhập API Key của dịch vụ giải CAPTCHA."})
        
    req_session = requests.Session()
    login_success, message = do_login(req_session, data.get('baseUrl'), data.get('username'), data.get('password'))
    
    if login_success:
        session['husc_cookies'] = requests.utils.dict_from_cookiejar(req_session.cookies)
        session['base_url'] = data.get('baseUrl')
        session['api_key'] = api_key
        return jsonify({"success": True, "student_name": message})
    else:
        return jsonify({"success": False, "message": message})

@app.route("/register-sequentially", methods=['POST'])
def handle_sequential_registration():
    if 'husc_cookies' not in session or 'api_key' not in session:
        return jsonify({"success": False, "message": "Phiên đăng nhập đã hết hạn."})

    data = request.json
    course_list = data.get('courseList', [])
    max_retries = data.get('maxRetries', 1)
    base_url = session['base_url']
    api_key = session['api_key']

    captcha_solver = AnticaptchaTopApi(api_key)
    req_session = requests.Session()
    req_session.cookies.update(session['husc_cookies'])
    
    results = []

    for course_id in course_list:
        attempts = 0
        success = False
        final_message = "Chưa thử"
        
        while not success and attempts < max_retries:
            attempts += 1
            print(f"[{course_id}] Đang thử lần {attempts}/{max_retries}...")
            try:
                details_page_url = f"{base_url}Course/Details/{course_id}/"
                registration_form_url = f"{base_url}Studying/CourseRegistration/{course_id}/"
                form_headers = {'Referer': details_page_url, 'X-Requested-With': 'XMLHttpRequest'}
                form_response = req_session.get(registration_form_url, headers=form_headers)
                form_soup = BeautifulSoup(form_response.text, 'html.parser')
                
                reg_token_element = form_soup.select_one('#formCourseRegistration input[name="__RequestVerificationToken"]')
                captcha_img_tag = form_soup.select_one("#formCourseRegistration img")

                if not reg_token_element or not captcha_img_tag:
                    error_div = form_soup.find('div', {'class': 'alert-danger'})
                    final_message = error_div.get_text(strip=True) if error_div else "Không lấy được form (Lớp đầy/trùng lịch?)."
                    break

                reg_token = reg_token_element['value']
                captcha_url = base_url.rstrip('/') + captcha_img_tag['src']
                
                captcha_response = req_session.get(captcha_url)
                img_base64 = base64.b64encode(captcha_response.content).decode('utf-8')
                solve_result = captcha_solver.solve(img_base64)
                
                if not solve_result or not solve_result.get('status'):
                    final_message = f"Lần {attempts}: Lỗi giải CAPTCHA: {solve_result.get('log', 'N/A') if solve_result else 'N/A'}"
                    time.sleep(2)
                    continue

                solved_captcha_text = solve_result['captcha']
                
                registration_payload = {
                    '__RequestVerificationToken': reg_token, 'courseId': course_id, 'captcha': solved_captcha_text,
                }
                final_headers = {'Referer': details_page_url, 'Origin': base_url.rstrip('/'), 'X-Requested-With': 'XMLHttpRequest'}
                
                final_response = req_session.post(base_url + "studying/CourseRegistration", data=registration_payload, headers=final_headers)
                result_json = final_response.json()
                
                if result_json.get('Code') == 1:
                    success = True
                    final_message = result_json.get('Msg', 'Thành công!')
                    session['husc_cookies'] = requests.utils.dict_from_cookiejar(req_session.cookies)
                    session.modified = True
                else:
                    final_message = f"Lần {attempts}: {result_json.get('Msg', 'Lỗi không rõ')}"
                    if "đầy" in final_message or "trùng lịch" in final_message:
                        break
                    time.sleep(2)

            except Exception as e:
                final_message = f"Lần {attempts}: Lỗi hệ thống: {e}"
                time.sleep(2)

        results.append({"courseId": course_id, "success": success, "message": final_message})
        # Thêm độ trễ giữa các môn học khác nhau
        time.sleep(1)

    return jsonify({"results": results})

if __name__ == "__main__":
    app.run(debug=True, port=5000)
