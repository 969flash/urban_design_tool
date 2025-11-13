# Urban Design Tool – 코드 컨벤션과 프로젝트 가이드

본 문서는 Rhino 8, Grasshopper (GhPython Python 3) 환경에서 동작하는 본 저장소의 공통 컨벤션을 정의합니다. 중복 유틸과 상수를 통합하여 유지보수를 단순화하기 위한 기준입니다.

## 개발 환경
- Rhino 8
- Grasshopper GhPython (Python 3)
- 주요 라이브러리 별칭
  - `import Rhino.Geometry as geo`
  - `import ghpythonlib.components as ghcomp`

## 모듈 구성
- 유틸리티: `src/utils.py`
  - 모든 공용 함수는 여기서 관리합니다.
- 상수: `src/constants.py`
  - 전역적인 숫자/레이어/패턴 파라미터는 여기서만 정의합니다. 하드코딩 금지.

## 네이밍 규칙
- 함수/변수: `snake_case` (예: `get_road_width`, `centerline_curve`)
- 클래스: `PascalCase` (예: `RoadProcessor`, `LineFactory`)
- 상수: `UPPER_SNAKE_CASE` (예: `TOL`, `LANE_PAINT_LENGTH`)
- 내부 구현(비공개) 메서드/클래스: `_leading_underscore` (예: `_ensure_layer`)
- Rhino/GH 별칭: `geo`, `ghcomp`

## 타입 힌트
- `typing`의 `List`, `Tuple`, `Optional`, `Union` 등을 적극 사용합니다.
- 복잡한 타입은 별칭으로 정의합니다. 예: `CurveLike = Union[geo.Curve, List[geo.Curve]]`
- 반환 타입이 `None`을 포함할 경우 `Optional[...]` 사용.

## Docstring (Google Style)
- 모든 함수/클래스/메서드에 한국어 Docstring을 권장합니다.
- 형식:
  """
  기능 요약 한 줄.

  Args:
      arg1 (geo.Curve): 설명.
      arg2 (float): 설명.

  Returns:
      geo.Curve: 설명.

  Raises:
      ValueError: 설명.
  """

## 주석
- 구현 배경/의도를 한국어로 `#` 주석으로 남깁니다.
- 파일 상단 인코딩 명시: `# -*- coding: utf-8 -*-`
- 논리적 블록을 장식 주석으로 구분합니다.

## 임포트 순서
1. Python 표준 라이브러리 (예: `math`, `functools`)
2. 서드파티 라이브러리 (예: `Rhino`, `ghpythonlib`)
3. 프로젝트 내부 모듈 (예: `from constants import ...`, `import utils`)

## 유틸/상수 통합 정책
- 중복 유틸은 `src/utils.py`로 이동/병합합니다.
  - 예: `move_brep`, `get_outside_perp_vec_from_pt`, `get_outline_from_closed_brep`, 영역 오프셋/불리언, 레이어 헬퍼 등.
  - Landuse에서 공용화 가능한 함수(`extrude_srf`, `is_point_on_srf`, `get_point_inside_face`, 레이어/Face 변환 유틸 등)도 `utils.py`에 존재합니다.
  
  - 현재는 `from utils import *`, `from constants import *`로 재노출되는 호환 레이어입니다.
- 상수는 반드시 `src/constants.py`에서만 정의/수정합니다.

## Rhino/GH 특이사항
- Rhino/GH 모듈 임포트(`Rhino`, `ghpythonlib`, `scriptcontext`)는 IDE에서 경고가 날 수 있으나, GH 환경에서 정상 동작합니다.
- 오프셋/불리언은 RhinoCommon/Clipper 양쪽 전략을 유틸에서 제공합니다. 필요 시 fallback을 고려하세요.

## 예시: 간단한 유틸 Docstring
```python
# -*- coding: utf-8 -*-
import Rhino.Geometry as geo

def move_brep(brep: geo.Brep, vector: geo.Vector3d) -> geo.Brep:
    """Brep를 주어진 벡터만큼 이동시킨 복사본을 반환합니다.

    Args:
        brep (geo.Brep): 이동할 원본 Brep.
        vector (geo.Vector3d): 이동 벡터.

    Returns:
        geo.Brep: 이동된 Brep 복사본.
    """
    moved = brep.Duplicate()
    moved.Translate(vector)
    return moved
```

## 변경 점 요약 (통합 작업)
- `utils.py`에 누락된 공용 함수 추가: `move_brep`, `get_outside_perp_vec_from_pt`, `get_outline_from_closed_brep` 등.
- Landuse 관련 반복 유틸을 `utils.py`로 추출: `extrude_srf`, `is_point_on_srf`, `get_point_inside_face`, `get_layer_surfaces`, 레이어 유틸 등.
  
- 각 모듈은 `utils.py`와 `constants.py`만 참조하도록 점진 정리.

## 권장 워크플로우
- 새 유틸이 필요하면 `utils.py`에 추가하고, 한국어 Docstring/타입 힌트를 작성합니다.
- 새 상수가 필요하면 `constants.py`에 정의하고, 모듈에서 이를 임포트합니다.
- 기존 파일을 정리할 때는, 먼저 유틸/상수 참조로 바꾸고, 지역 중복 구현을 제거합니다.
