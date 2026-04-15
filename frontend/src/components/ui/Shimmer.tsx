"use client";

export function Shimmer() {
  return (
    <div className="space-y-3 animate-pulse">
      <div className="h-4 bg-gradient-to-r from-gray-700 via-gray-600 to-gray-700 rounded w-3/4"></div>
      <div className="h-4 bg-gradient-to-r from-gray-700 via-gray-600 to-gray-700 rounded w-5/6"></div>
      <div className="h-4 bg-gradient-to-r from-gray-700 via-gray-600 to-gray-700 rounded w-4/5"></div>
    </div>
  );
}
