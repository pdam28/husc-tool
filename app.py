import requests
from bs4 import BeautifulSoup
from PIL import Image
import io
import base64
from flask import Flask, render_template, request, jsonify, session

app = Flask(__name__)
app.secret_key = 'a-very-very-secret-key-for-multi-university-tool' 

def do_login(req_session, base_url, username, password):
    """Hàm đăng nhập, trả về (True, Tên SV) hoặc (False, Thông báo lỗi)."""
    try:
        login_post_url = base_url + "Account/Login"
        # Truy cập trang chủ của trường đã chọn để lấy token
        response = req_session.get(base_url)
        soup = BeautifulSoup(response.text, 'html.parser')
        token = soup.find('input', {'name': '__RequestVerificationToken'})['value']
        
        payload = {
            '__RequestVerificationToken': token,
            'loginID': username,
            'password': password,
        }
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

@app.route("/")
def index():
    """Hiển thị trang chủ."""
    return render_template("index.html")

@app.route("/login", methods=['POST'])
def handle_login():
    data = request.json
    base_url = data.get('baseUrl')
    username = data.get('username')
    password = data.get('password')
    
    if not base_url:
        return jsonify({"success": False, "message": "Vui lòng chọn trường."})
        
    req_session = requests.Session()
    login_success, message = do_login(req_session, base_url, username, password)
    
    if login_success:
        # Lưu cookie và base_url vào session của Flask
        session['husc_cookies'] = requests.utils.dict_from_cookiejar(req_session.cookies)
        session['base_url'] = base_url 
        return jsonify({"success": True, "student_name": message})
    else:
        return jsonify({"success": False, "message": message})

@app.route("/get-captcha", methods=['POST'])
def get_captcha():
    if 'husc_cookies' not in session or 'base_url' not in session:
        return jsonify({"success": False, "message": "Phiên đăng nhập đã hết hạn."})

    data = request.json
    course_id = data.get('courseId')
    base_url = session['base_url'] # Lấy base_url từ session
    
    req_session = requests.Session()
    req_session.cookies.update(session['husc_cookies'])

    try:
        details_page_url = f"{base_url}Course/Details/{course_id}/"
        registration_form_url = f"{base_url}Studying/CourseRegistration/{course_id}/"
        form_headers = {'Referer': details_page_url, 'X-Requested-With': 'XMLHttpRequest'}
        form_response = req_session.get(registration_form_url, headers=form_headers)
        
        form_soup = BeautifulSoup(form_response.text, 'html.parser')
        reg_token_element = form_soup.select_one('#formCourseRegistration input[name="__RequestVerificationToken"]')
        
        if not reg_token_element:
            return jsonify({"success": False, "message": "Không lấy được form. Lớp có thể đã đầy/trùng lịch."})
        
        session['registration_token'] = reg_token_element['value']
        session['current_course_id'] = course_id

        captcha_img_tag = form_soup.select_one("#formCourseRegistration img")
        captcha_url = base_url.rstrip('/') + captcha_img_tag['src']
        captcha_response = req_session.get(captcha_url)
        
        img_b64 = base64.b64encode(captcha_response.content).decode('utf-8')
        img_data_url = f"data:image/jpeg;base64,{img_b64}"

        return jsonify({"success": True, "captcha_image_b64": img_data_url})
    except Exception as e:
        return jsonify({"success": False, "message": f"Lỗi khi lấy CAPTCHA: {e}"})

@app.route("/submit", methods=['POST'])
def submit_registration():
    if 'husc_cookies' not in session or 'base_url' not in session:
        return jsonify({"success": False, "message": "Phiên đăng nhập đã hết hạn."})

    data = request.json
    captcha_text = data.get('captchaText')
    base_url = session['base_url']
    registration_post_url = base_url + "studying/CourseRegistration"
    
    req_session = requests.Session()
    req_session.cookies.update(session['husc_cookies'])

    registration_payload = {
        '__RequestVerificationToken': session['registration_token'],
        'courseId': session['current_course_id'],
        'captcha': captcha_text,
    }
    
    details_page_url = f"{base_url}Course/Details/{session['current_course_id']}/"
    final_headers = {
        'Referer': details_page_url,
        'Origin': base_url.rstrip('/'),
        'X-Requested-With': 'XMLHttpRequest'
    }

    try:
        final_response = req_session.post(registration_post_url, data=registration_payload, headers=final_headers)
        result_json = final_response.json()
        
        return jsonify({"success": result_json.get('Code') == 1, "message": result_json.get('Msg', 'Không có phản hồi.')})
    except Exception as e:
        return jsonify({"success": False, "message": f"Lỗi khi gửi đăng ký: {e}"})

if __name__ == "__main__":
    app.run(debug=True, port=5000)