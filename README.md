# TD DeMark Exhaustion Lab

Yahoo Finance 데이터를 기반으로 고점 후보와 저점 후보를 동시에 추적하는 Streamlit 대시보드입니다. 기본 화면은 정확도 우선으로 동작하며, TD Sequential/Combo 공개식 근사, MFI divergence, Bollinger/STARC 재진입이 합류한 핵심 신호만 깔끔하게 표시합니다.

## 주의

- 이 앱은 DeMARK 공식 상용 지표 구현이 아닙니다. TD Combo, STARC, Camouflage 표시는 공개적으로 알려진 규칙을 조합한 educational approximation입니다.
- 현재 로컬 환경의 SSL 인증서 체인 문제 때문에 Yahoo 요청은 `curl_cffi` 세션에서 `verify=False`로 실행합니다.
- 신호는 투자 조언이 아니라 추세 소진 후보를 빠르게 검토하기 위한 분석 보조 자료입니다.

## 화면 해석

- `Top Score`는 고점 후보 점수입니다. TD Sell 9/13과 MFI 하락 다이버전스 또는 상단 Bollinger/STARC 재진입이 겹치면 기본 차트에 표시됩니다.
- `Bottom Score`는 저점 후보 점수입니다. TD Buy 9/13과 MFI 상승 다이버전스 또는 하단 Bollinger/STARC 재진입이 겹치면 기본 차트에 표시됩니다.
- `Top Pressure`/`Bottom Pressure` 리본은 7/8/9/13 진행 상태를 압축해서 보여줍니다. 리본이 커지고 핵심 마커가 찍히면 후보 신뢰도가 올라갑니다.
- `Precision` 모드는 기본값입니다. 강한 합류 신호만 표시해 노이즈를 줄입니다.
- `Balanced` 모드는 9/13과 확인된 7/8 경보를 표시합니다.
- `Debug` 모드는 `S7/S8/S9`, `B7/B8/B9`, `D7/D8/D9/D13`, `C7/C8/C9/C13` 전체 raw 진행을 차트에 표시합니다.
- `신호 로그` 탭에서는 기본 차트에 숨겨진 7/8/9/13 raw 진행까지 표로 확인할 수 있습니다.
- TD 단독 신호보다 MFI divergence, 밴드 재진입, 직전 지지/저항을 함께 보는 방식으로 사용합니다.

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
- 기본 차트는 최근 900개 행만 렌더링하고, 핵심 마커는 방향별 최대 40개로 제한합니다.
- 스캐너는 최근 20봉 안의 qualified signal 중 가장 강한 이벤트를 기준으로 정렬합니다.
- 스캐너 기본 목록은 `SPY, QQQ, AAPL, MSFT, NVDA, TSLA, BTC-USD, ETH-USD`이며 최대 25개 티커까지 처리합니다.

## 참고

- DeMARK Sequential: https://demark.com/sequential-indicator/
- DeMARK indicator list: https://demark.com/indicators-list/
- yfinance download API: https://ericpien.github.io/yfinance/reference/api/yfinance.download.html
- Streamlit Plotly chart API: https://docs.streamlit.io/develop/api-reference/charts/st.plotly_chart
