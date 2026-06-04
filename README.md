# TD DeMark Exhaustion Lab

Yahoo Finance 데이터를 기반으로 TD Sequential/Combo 계열의 공개식 근사 신호, MFI divergence, Bollinger squeeze/release, STARC-style bands를 함께 보는 Streamlit 대시보드입니다.

## 주의

- 이 앱은 DeMARK 공식 상용 지표 구현이 아닙니다. TD Combo, STARC, Camouflage 표시는 공개적으로 알려진 규칙을 조합한 educational approximation입니다.
- 현재 로컬 환경의 SSL 인증서 체인 문제 때문에 Yahoo 요청은 `curl_cffi` 세션에서 `verify=False`로 실행합니다.
- 신호는 투자 조언이 아니라 추세 소진 후보를 빠르게 검토하기 위한 분석 보조 자료입니다.

## 실행

```powershell
cd C:\Users\3964\Downloads\td_demark_app
powershell -NoProfile -ExecutionPolicy Bypass -File T:\PythonBox\run-python.ps1 -m streamlit run app.py
```

## 테스트

```powershell
cd C:\Users\3964\Downloads\td_demark_app
powershell -NoProfile -ExecutionPolicy Bypass -File T:\PythonBox\run-python.ps1 -m pytest
```

## 구현 메모

- 데이터 로딩은 `yfinance`를 우선 사용하고, 실패하면 Yahoo Finance raw chart API로 fallback합니다.
- Streamlit 데이터 로딩에는 `@st.cache_data(ttl=60)`를 적용해 탭 전환과 반복 스캔 때 불필요한 Yahoo 요청을 줄입니다.
- TD Setup은 Pandas vector 연산, Countdown/Combo는 NumPy 배열 기반 단일 순회 상태 기계로 계산합니다.
- 스캐너 기본 목록은 `SPY, QQQ, AAPL, MSFT, NVDA, TSLA, BTC-USD, ETH-USD`이며 최대 25개 티커까지 처리합니다.

## 참고

- DeMARK Sequential: https://demark.com/sequential-indicator/
- DeMARK indicator list: https://demark.com/indicators-list/
- yfinance download API: https://ericpien.github.io/yfinance/reference/api/yfinance.download.html
- Streamlit Plotly chart API: https://docs.streamlit.io/develop/api-reference/charts/st.plotly_chart
