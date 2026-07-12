import cv2
import numpy as np
import mss
import keyboard
import time

def auto_fishing_debug():
    monitor = {"top": 100, "left": 500, "width": 800, "height": 50}
    
    with mss.mss() as sct:
        print("디버깅 모드 시작... (종료하려면 디버깅 창이 선택된 상태에서 'Q'를 누르세요)")
        
        while True:
            # 1. 캡처 및 변환
            screen = np.array(sct.grab(monitor))
            img_bgr = cv2.cvtColor(screen, cv2.COLOR_BGRA2BGR)
            hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)

            # 2. 색상 마스크 생성
            mint_mask = cv2.inRange(hsv, np.array([70, 100, 100]), np.array([90, 255, 255]))
            yellow_mask = cv2.inRange(hsv, np.array([20, 100, 100]), np.array([40, 255, 255]))

            # 3. 좌표 계산
            mint_x = get_center_x(mint_mask)
            yellow_x = get_center_x(yellow_mask)

            # --- [디버깅: 시각화 요소 추가] ---
            
            # 민트색 X 좌표에 민트색(BGR: 255, 255, 0) 세로선 긋기
            if mint_x is not None:
                cv2.line(img_bgr, (mint_x, 0), (mint_x, monitor["height"]), (255, 255, 0), 2)
                
            # 노란색 X 좌표에 노란색(BGR: 0, 255, 255) 세로선 긋기
            if yellow_x is not None:
                cv2.line(img_bgr, (yellow_x, 0), (yellow_x, monitor["height"]), (0, 255, 255), 2)

            # 콘솔에 좌표 출력
            print(f"Mint X: {mint_x} | Yellow X: {yellow_x}")

            # 3개의 디버깅 창 띄우기
            cv2.imshow("Tracking View", img_bgr)      # 원본 화면 + 추적 선
            cv2.imshow("Mint Mask", mint_mask)        # 민트색 인식률 확인용 흑백 화면
            cv2.imshow("Yellow Mask", yellow_mask)    # 노란색 인식률 확인용 흑백 화면

            # -------------------------------

            # 키보드 제어 로직 (이전과 동일, 필요시 주석 처리하고 눈으로만 확인)
            if mint_x is not None and yellow_x is not None:
                if yellow_x < mint_x - 5:
                    keyboard.release('a')
                    keyboard.press('d')
                elif yellow_x > mint_x + 5:
                    keyboard.release('d')
                    keyboard.press('a')
                else:
                    keyboard.release('a')
                    keyboard.release('d')

            # 디버깅 창 업데이트 및 Q키 종료 처리 (필수)
            # waitKey(1)이 있어야 cv2.imshow 창이 화면에 그려집니다.
            if cv2.waitKey(1) & 0xFF == ord('q'):
                keyboard.release('a')
                keyboard.release('d')
                break

        # 루프 종료 시 모든 창 닫기
        cv2.destroyAllWindows()

def get_center_x(mask):
    moments = cv2.moments(mask)
    if moments["m00"] != 0:
        return int(moments["m10"] / moments["m00"])
    return None

if __name__ == "__main__":
    auto_fishing_debug()