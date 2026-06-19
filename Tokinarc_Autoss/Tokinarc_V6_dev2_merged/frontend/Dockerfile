# Tokinarc V6 — frontend/Dockerfile
# Build static React (Vite) rồi ghi vào volume frontend_dist (compose mount /app/dist).
# Nginx serve dist này ở cổng internal.

FROM node:20-alpine AS build
WORKDIR /app

# Cài deps trước (layer cache: chỉ rebuild khi package*.json đổi)
COPY package.json package-lock.json* ./
RUN npm ci

# Build thật: tsc --noEmit && vite build → /app/dist
COPY . .
RUN npm run build

# Stage 2: image gọn, chỉ chứa dist + copy ra volume khi container chạy.
FROM alpine:3
WORKDIR /app
COPY --from=build /app/dist ./dist
# Compose mount volume frontend_dist vào /app/dist → copy build vào volume rồi thoát.
CMD ["sh", "-c", "cp -r dist/* /app/dist/ && echo 'FE build copied to volume.'"]
