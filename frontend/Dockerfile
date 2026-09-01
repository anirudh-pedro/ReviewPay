FROM node:22-alpine AS build
WORKDIR /web
COPY package*.json ./
RUN npm ci
COPY . .
ARG VITE_API_BASE_URL=
ARG VITE_API_PREFIX=/api
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL VITE_API_PREFIX=$VITE_API_PREFIX
RUN npm run build

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /web/dist /usr/share/nginx/html
EXPOSE 80
