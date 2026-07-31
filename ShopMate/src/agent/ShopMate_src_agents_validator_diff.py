import os
import re
import asyncio
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
import statistics

# 가정: 프로젝트 내부 모듈 임포트
# from src.database import DatabaseSession, ProductPriceLog
# from src.config import Config

@dataclass
class PriceDataPoint:
    source: str          # 예: 'naver_shopping', 'cafe_real_trade', 'official_site'
    price: float
    currency: str        # 'KRW'
    timestamp: datetime
    reliability_score: float # 0.0 ~ 1.0 (신뢰도 점수)
    raw_text: str        # 원본 텍스트 (검증용)
    url: str

class ValidatorAgent:
    """
    가격 검증 에이전트 (v0.2)
    - 외부 오픈마켓 가격뿐만 아니라 네이버/다음 카페 등의 커뮤니티 실거래가를 수집·분석
    - 신뢰도 가중치를 적용하여 '공정 가격 (Fair Price)' 산출
    - 이상치 (사기, 과도한 홍보) 필터링
    """

    def __init__(self, db_session=None):
        self.db = db_session
        # 신뢰도 가중치 설정 (정책에 따라 조정 가능)
        self.WEIGHTS = {
            'official_site': 0.7,      # 공식 쇼핑몰 정가
            'open_market': 0.8,        # 오픈마켓 최저가
            'cafe_verified': 0.95,     # 카페 내 구매 인증된 실거래가
            'cafe_mention': 0.5,       # 카페 내 단순 언급 가격
            'used_market': 0.6         # 중고 거래 가격
        }

    async def validate_product_price(self, product_id: str, product_name: str) -> Dict:
        """
        특정 상품의 가격을 다각도로 검증하여 공정 가격을 반환
        """
        print(f"[Validator] {product_name} 에 대한 가격 검증 시작...")
        
        # 1. 데이터 수집 (Hunter Agent 로부터 받은 데이터 + 직접 크롤링)
        # 여기서는 Hunter 가 수집한 데이터를 받아온다고 가정
        raw_data_points = await self._gather_price_data(product_name)
        
        if not raw_data_points:
            return {"status": "error", "message": "수집된 가격 데이터가 없습니다."}

        # 2. 데이터 정제 및 신뢰도 부여
        cleaned_points = []
        for point in raw_data_points:
            score = self._calculate_reliability(point)
            if score > 0.3: # 신뢰도가 너무 낮은 데이터는 제외
                point.reliability_score = score
                cleaned_points.append(point)

        if not cleaned_points:
            return {"status": "error", "message": "검증 가능한 데이터가 부족합니다."}

        # 3. 통계적 이상치 제거 (IQR 방식 등)
        filtered_points = self._remove_outliers(cleaned_points)

        if not filtered_points:
            return {"status": "error", "message": "이상치 제거 후 유효 데이터가 없습니다."}

        # 4. 가중치 평균을 통한 공정 가격 산출
        fair_price = self._calculate_weighted_average(filtered_points)
        min_price = min(p.price for p in filtered_points)
        max_price = max(p.price for p in filtered_points)
        
        # 5. 결과 저장 및 반환
        result = {
            "product_id": product_id,
            "product_name": product_name,
            "fair_price": round(fair_price, 0),
            "min_price": round(min_price, 0),
            "max_price": round(max_price, 0),
            "sample_count": len(filtered_points),
            "sources": list(set(p.source for p in filtered_points)),
            "updated_at": datetime.now().isoformat()
        }

        # DB 저장 로직 (주석 처리됨)
        # await self._save_to_db(product_id, result)
        
        print(f"[Validator] 검증 완료: 공정 가격 {result['fair_price']}원 (샘플: {result['sample_count']}개)")
        return result

    async def _gather_price_data(self, product_name: str) -> List[PriceDataPoint]:
        """
        다양한 소스에서 가격 데이터를 수집
        - 오픈마켓 (Hunter Agent 연동)
        - 네이버 카페, 다음 카페 (직접 크롤링 또는 API)
        """
        points = []
        
        # TODO: 실제 구현 시 Hunter Agent 와 연동하거나 직접 크롤러 호출
        # 예시: mock data 생성
        
        # 1. 오픈마켓 데이터 (가정)
        points.append(PriceDataPoint(
            source='open_market', price=150000, currency='KRW',
            timestamp=datetime.now(), reliability_score=0.0, # 추후 계산
            raw_text="오픈마켓 최저가", url="https://..."
        ))

        # 2. 네이버 카페 데이터 (시뮬레이션)
        # 카페명: "스마트홈 공동구매", 게시글: "XX 제품 구매후기 입니다. 13 만원에 샀어요."
        points.append(PriceDataPoint(
            source='cafe_verified', price=130000, currency='KRW',
            timestamp=datetime.now(), reliability_score=0.0,
            raw_text="[구매인증] XX 제품 13 만원에 구매 완료. 인증사진 첨부.", 
            url="https://cafe.naver.com/..."
        ))

        # 3. 다음 카페 데이터 (시뮬레이션)
        # 카페명: "알뜰 쇼핑 정보", 게시글: "XX 제품 14 만 5 천원 공동구매 진행중"
        points.append(PriceDataPoint(
            source='cafe_verified', price=145000, currency='KRW',
            timestamp=datetime.now(), reliability_score=0.0,
            raw_text="XX 제품 145,000 원 공동구매 모집. 입금 확인 즉시 발송.", 
            url="https://cafe.daum.net/..."
        ))

        # 4. 의심스러운 데이터 (필터링 테스트용)
        points.append(PriceDataPoint(
            source='cafe_mention', price=50000, currency='KRW',
            timestamp=datetime.now(), reliability_score=0.0,
            raw_text="XX 제품 5 만원에 팝니다. 사기 아님.", 
            url="https://..."
        ))

        return points

    def _calculate_reliability(self, point: PriceDataPoint) -> float:
        """
        소스와 콘텐츠 분석을 통해 신뢰도 점수 계산
        """
        base_score = self.WEIGHTS.get(point.source, 0.5)
        
        # 콘텐츠 분석을 통한 추가 가감점
        text = point.raw_text.lower()
        
        # 구매 인증 키워드 발견 시 가산점
        if any(k in text for k in ['구매인증', '인증샷', '입금완료', '받았습니다']):
            base_score = min(base_score + 0.1, 1.0)
        
        # 사기 의심 키워드 발견 시 감점
        if any(k in text for k in ['급판', '사기아님', '무조건싸게']):
            base_score = max(base_score - 0.3, 0.1)
            
        return base_score

    def _remove_outliers(self, data_points: List[PriceDataPoint]) -> List[PriceDataPoint]:
        """
        IQR (Interquartile Range) 방식을 사용하여 통계적 이상치 제거
        """
        if len(data_points) < 4:
            return data_points # 데이터가 적으면 모두 유지

        prices = [p.price for p in data_points]
        q1 = statistics.quantiles(prices, n=4)[0]
        q3 = statistics.quantiles(prices, n=4)[2]
        iqr = q3 - q1
        
        lower_bound = q1 - (1.5 * iqr)
        upper_bound = q3 + (1.5 * iqr)
        
        filtered = [p for p in data_points if lower_bound <= p.price <= upper_bound]
        return filtered

    def _calculate_weighted_average(self, data_points: List[PriceDataPoint]) -> float:
        """
        신뢰도 가중치를 적용한 평균 가격 계산
        """
        total_weight = sum(p.reliability_score for p in data_points)
        if total_weight == 0:
            return statistics.mean([p.price for p in data_points])
            
        weighted_sum = sum(p.price * p.reliability_score for p in data_points)
        return weighted_sum / total_weight

    async def _save_to_db(self, product_id: str, result: Dict):
        """
        검증 결과를 DB 에 저장 (구현 예정)
        """
        pass

# --- 테스트 실행 ---
if __name__ == "__main__":
    agent = ValidatorAgent()
    # 비동기 테스트
    result = asyncio.run(agent.validate_product_price("P12345", "스마트 홈 허브"))
    print(f"\n최종 검증 결과:\n{result}")
