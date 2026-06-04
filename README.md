# TD DeMark Exhaustion Lab

Yahoo Finance 데이터를 기반으로 고점 후보와 저점 후보를 동시에 추적하는 Streamlit 대시보드입니다. 기본 화면은 `Precision` 모드이며, TD Sequential/Combo 공개식 근사치와 MFI divergence, Bollinger/STARC 재진입 필터가 겹치는 핵심 신호만 차트에 표시합니다.

## 주의

- 이 앱은 DeMARK 공식 상용 지표가 아닙니다. TD Combo, STARC, Camouflage 표시는 공개적으로 알려진 규칙을 조합한 `educational approximation`입니다.
- 로컬 환경의 Yahoo 요청 안정성을 위해 `curl_cffi` 세션에서 SSL 검증을 우회합니다. 즉, 가격 데이터 요청은 `verify=False`로 실행됩니다.
- 표시 신호는 투자 조언이 아니라 추세 소진 후보를 빠르게 좁히기 위한 보조 분석 자료입니다.

## 화면 해석

- `Top Score`: 고점 후보 점수입니다. TD Sell 9/13, Combo 13, MFI 하락 divergence, 상단 밴드/STARC 이탈 후 재진입이 겹칠수록 올라갑니다.
- `Bottom Score`: 저점 후보 점수입니다. TD Buy 9/13, Combo 13, MFI 상승 divergence, 하단 밴드/STARC 이탈 후 재진입이 겹칠수록 올라갑니다.
- `Top Pressure`와 `Bottom Pressure` 리본은 7/8/9/13 진행 상태를 압축해서 보여줍니다. 기본 차트 마커가 많아지지 않도록 7/8은 주로 리본과 신호 로그에서 확인합니다.
- `Precision`: 기본 모드입니다. 강한 합류 신호만 핵심 마커로 표시합니다.
- `Balanced`: 9/13과 확인된 7/8 경보를 같이 봅니다.
- `Debug`: `S7/S8/S9`, `B7/B8/B9`, `D7/D8/D9/D13`, `C7/C8/C9/C13` raw 진행을 모두 표시합니다.

## 대형 스크리너

`멀티 스캐너` 화면에서 다음 유니버스를 선택할 수 있습니다.

- `Custom Watchlist`: 사이드바에 입력한 최대 25개 심볼
- `NASDAQ100`: Wikipedia Nasdaq-100 구성 종목
- `KOSPI200`: Naver Finance KPI200 구성 종목, Yahoo 심볼은 `.KS`
- `KOSDAQ150`: Naver KQ150 갱신을 먼저 시도하되, 잘못된 KOSPI 목록이 반환되면 Investing.com KOSDAQ150 구성 종목으로 fallback, Yahoo 심볼은 `.KQ`

대형 유니버스는 자동 실행하지 않습니다. `Start Scan`을 눌렀을 때만 Yahoo 요청을 시작하고, 한 번의 Streamlit rerun마다 12개씩 처리합니다. 배치 내부 동시 요청은 최대 4개로 제한하며, 진행률과 현재 배치, 완료/실패 수, elapsed time을 화면에 표시합니다.

결과는 다음 탭으로 나뉩니다.

- `Top candidates`: 고점 후보 또는 `top_score > bottom_score`
- `Bottom candidates`: 저점 후보 또는 `bottom_score > top_score`
- `All / Failures`: 전체 결과와 실패 종목

내장 CSV는 `data/universes/*.csv`에 포함되어 있습니다. `Refresh Universe`는 현재 세션 목록만 갱신하고 CSV 파일은 자동 수정하지 않습니다.

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

- 데이터 로딩은 `yfinance`를 우선 사용하고, 실패하거나 빈 데이터가 오면 Yahoo Finance raw chart API로 fallback합니다.
- 단일 차트 데이터 캐시는 `@st.cache_data(ttl=60)`, 스캐너 가격 캐시는 `@st.cache_data(ttl=3600)`입니다.
- TD Setup은 Pandas vector 연산, Countdown/Combo는 NumPy 배열 기반 단일 순회 상태 기계로 계산합니다.
- 스캐너는 최근 20봉 안의 가장 강한 qualified signal을 기준으로 정렬합니다.

## 참고

- DeMARK Sequential: https://demark.com/sequential-indicator/
- DeMARK indicator list: https://demark.com/indicators-list/
- yfinance download API: https://ericpien.github.io/yfinance/reference/api/yfinance.download.html
- Streamlit Plotly chart API: https://docs.streamlit.io/develop/api-reference/charts/st.plotly_chart
- Nasdaq-100: https://en.wikipedia.org/wiki/Nasdaq-100
- Naver Finance KPI200: https://finance.naver.com/sise/entryJongmok.naver?code=KPI200&page=1
- Naver Finance KQ150: https://finance.naver.com/sise/entryJongmok.naver?code=KQ150&page=1
- Investing KOSDAQ150: https://ca.investing.com/indices/kosdaq-150-components
